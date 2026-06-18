from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
import subprocess
import threading
from typing import Any

from fastapi.testclient import TestClient
from pydantic import TypeAdapter
import pytest

from skidc.dispatcher.config import DispatchConfig
from skidc.dispatcher.protocol.client import ApiResult
from skidc.dispatcher.runtime.process import ProcessResult
from skidc.dispatcher.scheduler.loop import DispatcherLoop
from skidc.server import db
from skidc.server.app import app
from skidc.server.models import ProjectDetail, ProjectSummary, Settings


class InProcessClient:
    """A SkidcClient look-alike that talks to the FastAPI app via TestClient,
    so the whole dispatcher pipeline runs in one process with no network."""

    def __init__(self, http: TestClient):
        self.http = http
        self._summaries = TypeAdapter(list[ProjectSummary])

    def close(self) -> None:
        return None

    def list_projects(self) -> list[ProjectSummary]:
        response = self.http.get("/projects")
        response.raise_for_status()
        return self._summaries.validate_python(response.json())

    def get_project(self, project_id: str) -> ProjectDetail:
        response = self.http.get(f"/projects/{project_id}")
        response.raise_for_status()
        return ProjectDetail.model_validate(response.json())

    def get_settings(self) -> Settings:
        response = self.http.get("/settings")
        response.raise_for_status()
        return Settings.model_validate(response.json())

    def export_project(self, project_id: str) -> str:
        response = self.http.get(f"/projects/{project_id}/export?format=yaml")
        response.raise_for_status()
        return response.text

    def heartbeat(self, project_id: str, intent_id: str, worker: str) -> ApiResult:
        return self._post(f"/projects/{project_id}/intents/{intent_id}/heartbeat", {"worker": worker})

    def claim_reason(self, project_id: str, worker: str, trigger: str) -> ApiResult:
        return self._post(f"/projects/{project_id}/reason/claim", {"worker": worker, "trigger": trigger})

    def reason_heartbeat(self, project_id: str, worker: str) -> ApiResult:
        return self._post(f"/projects/{project_id}/reason/heartbeat", {"worker": worker})

    def release_reason(self, project_id: str, worker: str) -> ApiResult:
        return self._post(f"/projects/{project_id}/reason/release", {"worker": worker})

    def release(self, project_id: str, intent_id: str, worker: str) -> ApiResult:
        return self._post(f"/projects/{project_id}/intents/{intent_id}/release", {"worker": worker})

    def conclude(
        self,
        project_id: str,
        intent_id: str,
        worker: str,
        description: str,
        fact_fields: dict[str, str] | None = None,
    ) -> ApiResult:
        body = {"worker": worker, "description": description}
        if fact_fields:
            for key in ("scope", "vuln_type", "severity", "parent_fact"):
                value = fact_fields.get(key)
                if value:
                    body[key] = value
        return self._post(
            f"/projects/{project_id}/intents/{intent_id}/conclude",
            body,
        )

    def complete(self, project_id: str, from_ids: list[str], description: str, worker: str) -> ApiResult:
        return self._post(
            f"/projects/{project_id}/complete",
            {"from": from_ids, "description": description, "worker": worker},
        )

    def create_intent(self, project_id: str, from_ids: list[str], description: str, creator: str) -> ApiResult:
        return self._post(
            f"/projects/{project_id}/intents",
            {"from": from_ids, "description": description, "creator": creator, "worker": None},
        )

    def create_attack_path(
        self, project_id: str, name: str, fact_chain: list[str], description: str, severity: str = "medium",
    ) -> ApiResult:
        return self._post(
            f"/projects/{project_id}/attack-paths",
            {"name": name, "fact_chain": fact_chain, "description": description, "severity": severity},
        )

    def _post(self, path: str, payload: dict[str, Any]) -> ApiResult:
        response = self.http.post(path, json=payload)
        data = response.json() if response.headers.get("content-type", "").startswith("application/json") else None
        return ApiResult(response.status_code, data, response.text)


class LocalProcess:
    """Runs the mock worker command as a real local subprocess (no Docker)."""

    def __init__(self, command: list[str], env: dict[str, str]):
        self.command = command
        self.env = env
        self._process: subprocess.Popen[str] | None = None
        self._cancel_reason: str | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            self._process = subprocess.Popen(
                self.command,
                env={**os.environ, **self.env},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

    def communicate(self, timeout: float | None) -> ProcessResult:
        assert self._process is not None
        timed_out = False
        try:
            stdout, stderr = self._process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            self.kill()
            stdout, stderr = self._process.communicate()
        return ProcessResult(
            returncode=self._process.returncode,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            cancelled=self._cancel_reason is not None,
            cancel_reason=self._cancel_reason,
        )

    def kill(self) -> None:
        with self._lock:
            process = self._process
        if process is not None and process.poll() is None:
            process.kill()

    def cancel(self, reason: str) -> None:
        if self._cancel_reason is None:
            self._cancel_reason = reason
        self.kill()


class LocalContainerManager:
    """ContainerManager stand-in: no Docker, just runs mock commands locally and
    captures the graph-snapshot file writes the tasks would have injected."""

    def __init__(self) -> None:
        self.writes: list[tuple[str, str, str]] = []

    def close(self) -> None:
        return None

    def container_name(self, project_id: str) -> str:
        return f"local-{project_id}"

    def ensure_running(self, project_id: str) -> str:
        return self.container_name(project_id)

    def build_exec_process(
        self,
        _container_name: str,
        env: dict[str, str],
        command: list[str],
        timeout_seconds: int | None = None,
        kill_after_seconds: int = 5,
    ) -> LocalProcess:
        assert timeout_seconds is not None
        assert kill_after_seconds == 5
        return LocalProcess(command, env)

    def write_text_file(self, container_name: str, path: str, content: str) -> None:
        self.writes.append((container_name, path, content))

    def needs_completed_cleanup(self, _project_id: str) -> bool:
        return False

    def needs_stopped_cleanup(self, _project_id: str) -> bool:
        return False

    def managed_container_names(self) -> list[str]:
        return []


@pytest.fixture
def http_client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(db, "_db_path", None)
    db.configure(tmp_path / "skidc.db")
    with TestClient(app) as client:
        yield client


def phase(outcome: str, *, rules: list[dict[str, Any]] | None = None, zero_outcomes: list[str] | None = None) -> str:
    outcomes = {name: 0 for name in zero_outcomes or []}
    outcomes[outcome] = 1
    payload: dict[str, Any] = {"delay": [0, 0], "outcomes": outcomes}
    if rules is not None:
        payload["rules"] = rules
    return json.dumps(payload)


def mock_config(
    *,
    bootstrap: str,
    reason: str,
    explore: str,
    task_types: list[str] | None = None,
) -> DispatchConfig:
    return DispatchConfig.model_validate(
        {
            "server": "in-process",
            "runtime": {
                "interval": 1,
                "max_workers": 1,
                "max_running_projects": 1,
                "max_project_workers": 1,
                "healthcheck_timeout": 2,
                "prompt_group": "mock",
            },
            "tasks": {
                "bootstrap": {"timeout": 2, "conclude_timeout": 2},
                "reason": {"timeout": 2, "max_intents": 1},
                "explore": {"timeout": 2, "conclude_timeout": 2},
            },
            "container": {"image": "unused", "network_mode": "host", "completed_action": "stop"},
            "workers": [
                {
                    "name": "mock-worker",
                    "type": "mock",
                    "task_types": task_types or ["bootstrap", "reason", "explore"],
                    "max_running": 1,
                    "priority": 0,
                    "env": {
                        "MOCK_HEALTHCHECK": phase("ok"),
                        "MOCK_BOOTSTRAP": bootstrap,
                        "MOCK_REASON": reason,
                        "MOCK_EXPLORE_EXECUTE": explore,
                    },
                }
            ],
        }
    )


def make_loop(config: DispatchConfig, client: InProcessClient, containers: LocalContainerManager) -> DispatcherLoop:
    loop = DispatcherLoop.__new__(DispatcherLoop)
    loop.config = config
    loop.client = client
    loop.container_manager = containers
    loop.executor = ThreadPoolExecutor(max_workers=config.runtime.max_workers)
    loop.cleanup_executor = ThreadPoolExecutor(max_workers=1)
    loop.futures = {}
    loop.cleanup_futures = {}
    loop.reason_checkpoints = {}
    loop.runtime_project_ids = set()
    loop.worker_unhealthy_until = {}
    loop.worker_rejected_until = {}
    loop._log_state = {}
    loop._cleanup_pending = set()
    loop._inactive_cleanup_done = {}
    loop.project_cursor = 0
    return loop


def dispatch_and_wait(loop: DispatcherLoop) -> None:
    loop._reap_futures()
    summaries = loop.client.list_projects()
    loop._initialize_reason_checkpoints(summaries)
    loop._refresh_runtime_projects(summaries)
    loop._cancel_inactive_tasks(summaries)
    loop._queue_container_cleanups(summaries)
    loop._dispatch_available(summaries)
    assert loop.futures
    for future in list(loop.futures):
        future.result(timeout=10)
    loop._reap_futures()


def create_project(http: TestClient, *, bootstrap_enabled: bool = True) -> str:
    response = http.post(
        "/projects",
        json={"title": "integration", "origin": "start", "goal": "finish", "bootstrap_enabled": bootstrap_enabled},
    )
    assert response.status_code == 201
    return response.json()["project"]["id"]
