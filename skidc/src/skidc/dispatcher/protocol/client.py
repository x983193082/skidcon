from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import logging
import threading

from pydantic import TypeAdapter
import requests
from requests.adapters import HTTPAdapter

from skidc.server.models import Intent, ProjectDetail, ProjectSummary, Settings

LOG = logging.getLogger(__name__)


class ProtocolError(RuntimeError):
    def __init__(self, message: str, status_code: int, response_text: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text


@dataclass(slots=True)
class ApiResult:
    status_code: int
    data: Any | None = None
    text: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


class SkidcClient:
    def __init__(self, base_url: str, timeout: float = 10.0):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._summary_adapter = TypeAdapter(list[ProjectSummary])
        self._local = threading.local()
        self._sessions: dict[int, requests.Session] = {}
        self._sessions_lock = threading.Lock()

    def close(self) -> None:
        with self._sessions_lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.close()

    def list_projects(self) -> list[ProjectSummary]:
        response = self._session().get(self._url("/projects"), timeout=self._timeout)
        response.raise_for_status()
        return self._summary_adapter.validate_python(response.json())

    def get_project(self, project_id: str) -> ProjectDetail:
        response = self._session().get(self._url(f"/projects/{project_id}"), timeout=self._timeout)
        response.raise_for_status()
        return ProjectDetail.model_validate(response.json())

    def get_settings(self) -> Settings:
        response = self._session().get(self._url("/settings"), timeout=self._timeout)
        response.raise_for_status()
        return Settings.model_validate(response.json())

    def export_project(self, project_id: str) -> str:
        response = self._session().get(
            self._url(f"/projects/{project_id}/export"),
            params={"format": "yaml"},
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.text

    def heartbeat(self, project_id: str, intent_id: str, worker: str) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/intents/{intent_id}/heartbeat",
            json={"worker": worker},
        )

    def claim_reason(self, project_id: str, worker: str, trigger: str) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/reason/claim",
            json={"worker": worker, "trigger": trigger},
        )

    def reason_heartbeat(self, project_id: str, worker: str) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/reason/heartbeat",
            json={"worker": worker},
        )

    def release_reason(self, project_id: str, worker: str) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/reason/release",
            json={"worker": worker},
        )

    def release(self, project_id: str, intent_id: str, worker: str) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/intents/{intent_id}/release",
            json={"worker": worker},
        )

    def conclude(
        self,
        project_id: str,
        intent_id: str,
        worker: str,
        description: str,
        fact_fields: dict[str, str] | None = None,
    ) -> ApiResult:
        body: dict[str, Any] = {"worker": worker, "description": description}
        if fact_fields:
            for key in ("scope", "vuln_type", "severity", "parent_fact", "goal_type", "status"):
                value = fact_fields.get(key)
                if value:
                    body[key] = value
        return self._request_json(
            "POST",
            f"/projects/{project_id}/intents/{intent_id}/conclude",
            json=body,
        )

    def create_fact_direct(
        self,
        project_id: str,
        description: str,
        goal_type: str | None = None,
        status: str | None = None,
    ) -> ApiResult:
        body: dict[str, Any] = {"description": description}
        if goal_type:
            body["goal_type"] = goal_type
        if status:
            body["status"] = status
        return self._request_json(
            "POST",
            f"/projects/{project_id}/facts",
            json=body,
        )

    def complete(self, project_id: str, from_ids: list[str], description: str, worker: str) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/complete",
            json={"from": from_ids, "description": description, "worker": worker},
        )

    def create_intent(self, project_id: str, from_ids: list[str], description: str, creator: str) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/intents",
            json={"from": from_ids, "description": description, "creator": creator, "worker": None},
        )

    def create_attack_path(
        self, project_id: str, name: str, fact_chain: list[str], description: str, severity: str = "medium",
    ) -> ApiResult:
        return self._request_json(
            "POST",
            f"/projects/{project_id}/attack-paths",
            json={"name": name, "fact_chain": fact_chain, "description": description, "severity": severity},
        )

    def update_phase(self, project_id: str, phase: str) -> ApiResult:
        return self._request_json(
            "PUT",
            f"/projects/{project_id}/phase",
            json={"phase": phase},
        )

    def _request_json(self, method: str, path: str, json: dict[str, Any]) -> ApiResult:
        try:
            response = self._session().request(
                method,
                self._url(path),
                json=json,
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            LOG.warning("request failed method=%s path=%s error=%s", method, path, exc)
            return ApiResult(status_code=0, text=str(exc))
        data: Any | None = None
        if response.headers.get("content-type", "").startswith("application/json"):
            data = response.json()
        return ApiResult(status_code=response.status_code, data=data, text=response.text)

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is not None:
            return session

        session = requests.Session()
        adapter = HTTPAdapter(pool_connections=64, pool_maxsize=64, pool_block=False)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        self._local.session = session
        with self._sessions_lock:
            self._sessions[threading.get_ident()] = session
        return session
