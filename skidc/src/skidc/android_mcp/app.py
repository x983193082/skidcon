from __future__ import annotations

import json
import os
import re
import zipfile
from collections import OrderedDict, deque
from datetime import UTC, datetime
from ipaddress import ip_address
from pathlib import Path
from threading import BoundedSemaphore, Lock
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from skidc.android_mcp.adb import AdbController, AndroidCommandError
from skidc.android_mcp.auth import BearerTokenAuth
from skidc.android_mcp.mobile_analysis import (
    analyze_apk,
    frida_script_templates,
    lab_profiles,
    parse_network_import,
    tool_status,
)


MAX_FRIDA_OBSERVATIONS = 1_000
MAX_FRIDA_DETAILS_BYTES = 65_536
MAX_REVERSE_REPORTS_PER_ASSESSMENT = 100
MAX_ASSESSMENT_NAMESPACES = 64
MAX_FRIDA_HISTORY_BYTES = 16_000_000
MAX_REVERSE_HISTORY_BYTES = 16_000_000
MAX_NETWORK_EVENTS = 1_000
MAX_NETWORK_IMPORT_BYTES = 2_000_000
MAX_NETWORK_IMPORT_EVENTS = 1_000
MAX_NETWORK_BODY_PREVIEW = 8_192
MAX_NETWORK_EVENT_BYTES = 65_536
MAX_NETWORK_URL_CHARS = 8_192
MAX_NETWORK_NOTE_CHARS = 2_000
MAX_NETWORK_HEADERS = 100
MAX_NETWORK_HEADER_NAME_CHARS = 256
MAX_NETWORK_HEADER_VALUE_CHARS = 8_192
ASSESSMENT_ID_PATTERN = r"^[A-Za-z0-9._-]+$"
SENSITIVE_FIELD_NAMES = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "api-key",
    "x-api-key",
    "auth-token",
    "x-auth-token",
    "access-token",
    "x-access-token",
    "password",
    "passwd",
    "secret",
    "token",
}


class AssessmentHistoryStore:
    def __init__(
        self,
        *,
        max_assessments: int,
        max_items_per_assessment: int,
        max_total_bytes: int,
    ) -> None:
        self.max_assessments = max_assessments
        self.max_items_per_assessment = max_items_per_assessment
        self.max_total_bytes = max_total_bytes
        self._histories: OrderedDict[str, deque[tuple[dict[str, Any], int]]] = OrderedDict()
        self._total_bytes = 0

    @property
    def assessment_count(self) -> int:
        return len(self._histories)

    @property
    def total_bytes(self) -> int:
        return self._total_bytes

    def append(self, assessment_id: str, payload: dict[str, Any]) -> None:
        size = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        if size > self.max_total_bytes:
            raise ValueError(f"record exceeds history byte limit of {self.max_total_bytes}")
        if assessment_id in self._histories:
            history = self._histories.pop(assessment_id)
            self._histories[assessment_id] = history
        else:
            while len(self._histories) >= self.max_assessments:
                self._evict_oldest_assessment()
            history = deque()
            self._histories[assessment_id] = history
        while len(history) >= self.max_items_per_assessment:
            _, removed_size = history.popleft()
            self._total_bytes -= removed_size
        while self._total_bytes + size > self.max_total_bytes:
            self._evict_oldest_item()
        if assessment_id not in self._histories:
            history = deque()
            self._histories[assessment_id] = history
        history.append((payload, size))
        self._total_bytes += size

    def list(self, assessment_id: str) -> list[dict[str, Any]]:
        return [payload for payload, _ in self._histories.get(assessment_id, ())]

    def clear(self, assessment_id: str) -> int:
        history = self._histories.pop(assessment_id, ())
        removed = len(history)
        self._total_bytes -= sum(size for _, size in history)
        return removed

    def _evict_oldest_assessment(self) -> None:
        _, history = self._histories.popitem(last=False)
        self._total_bytes -= sum(size for _, size in history)

    def _evict_oldest_item(self) -> None:
        assessment_id, history = next(iter(self._histories.items()))
        _, removed_size = history.popleft()
        self._total_bytes -= removed_size
        if not history:
            del self._histories[assessment_id]


class AndroidMcpState:
    def __init__(self) -> None:
        self.controller = AdbController()
        self.auth = BearerTokenAuth()
        self.artifact_root = Path(os.environ.get("ANDROID_MCP_ARTIFACT_ROOT", Path.cwd())).resolve()
        self.network_events: deque[dict[str, Any]] = deque(maxlen=MAX_NETWORK_EVENTS)
        self.next_network_event_id = 1
        self.network_lock = Lock()
        self.reverse_reports = AssessmentHistoryStore(
            max_assessments=MAX_ASSESSMENT_NAMESPACES,
            max_items_per_assessment=MAX_REVERSE_REPORTS_PER_ASSESSMENT,
            max_total_bytes=MAX_REVERSE_HISTORY_BYTES,
        )
        self.reverse_lock = Lock()
        self.reverse_analysis_slots = BoundedSemaphore(1)
        self.frida_observations = AssessmentHistoryStore(
            max_assessments=MAX_ASSESSMENT_NAMESPACES,
            max_items_per_assessment=MAX_FRIDA_OBSERVATIONS,
            max_total_bytes=MAX_FRIDA_HISTORY_BYTES,
        )
        self.frida_lock = Lock()


state = AndroidMcpState()

app = FastAPI(
    title="Skidc Android MCP Bridge",
    description="Minimal Android emulator/app control bridge for authorized mobile testing",
    version="0.1.0",
)


def configure(
    *,
    adb_path: str = "adb",
    device_id: str | None = None,
    timeout: int = 20,
    artifact_root: Path | None = None,
    token_file: Path | None = None,
) -> None:
    auth = BearerTokenAuth.from_file(token_file)
    state.controller = AdbController(adb_path=adb_path, device_id=device_id, timeout=timeout)
    state.auth = auth
    if artifact_root is not None:
        state.artifact_root = artifact_root.resolve()


@app.middleware("http")
async def authenticate_bridge(request: Request, call_next):
    if request.url.path == "/health/live":
        return await call_next(request)
    auth_result = state.auth.authorize(request.headers.get("Authorization"))
    if auth_result == "missing":
        return JSONResponse(
            status_code=401,
            content={"detail": "Bearer token required"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    if auth_result == "invalid":
        return JSONResponse(
            status_code=403,
            content={"detail": "Bearer token rejected"},
        )
    return await call_next(request)


class PackageRequest(BaseModel):
    package: str = Field(min_length=1)

    @field_validator("package")
    @classmethod
    def validate_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class InstallRequest(BaseModel):
    apk_path: str = Field(min_length=1)
    reinstall: bool = True


class StartAppRequest(PackageRequest):
    activity: str | None = None


class TapRequest(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)


class SwipeRequest(BaseModel):
    x1: int = Field(ge=0)
    y1: int = Field(ge=0)
    x2: int = Field(ge=0)
    y2: int = Field(ge=0)
    duration_ms: int = Field(default=300, ge=0, le=10000)


class TextRequest(BaseModel):
    text: str


class KeyRequest(BaseModel):
    key: str = Field(min_length=1)


class LogcatRequest(BaseModel):
    lines: int = Field(default=200, ge=1, le=2000)


class NetworkEvent(BaseModel):
    method: str | None = Field(default=None, max_length=32)
    url: str = Field(max_length=MAX_NETWORK_URL_CHARS)
    status_code: int | None = None
    request_headers: dict[str, str] = Field(default_factory=dict)
    response_headers: dict[str, str] = Field(default_factory=dict)
    request_body_preview: str | None = None
    response_body_preview: str | None = None
    note: str | None = Field(default=None, max_length=MAX_NETWORK_NOTE_CHARS)

    @field_validator("request_headers", "response_headers")
    @classmethod
    def validate_headers(cls, value: dict[str, str]) -> dict[str, str]:
        _validate_headers(value)
        return value

    @model_validator(mode="after")
    def validate_event_size(self) -> "NetworkEvent":
        _validate_network_event_size(self.model_dump())
        return self


class ProxyRequest(BaseModel):
    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(ge=1, le=65535)

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        text = value.strip()
        if not text or any(character.isspace() for character in text):
            raise ValueError("host must be an IPv4 address, IPv6 address, or hostname")
        if text.startswith("[") or text.endswith("]"):
            if not (text.startswith("[") and text.endswith("]")):
                raise ValueError("host must be an IPv4 address, IPv6 address, or hostname")
            try:
                address = ip_address(text[1:-1])
            except ValueError as exc:
                raise ValueError("brackets are only valid around an IPv6 address") from exc
            if address.version != 6:
                raise ValueError("brackets are only valid around an IPv6 address")
            return str(address)
        try:
            return str(ip_address(text))
        except ValueError:
            pass
        if text.endswith(".."):
            raise ValueError("host may contain at most one trailing root dot")
        text = text.removesuffix(".")
        if len(text) > 253 or ":" in text or "/" in text or "\\" in text:
            raise ValueError("host must be an IPv4 address, IPv6 address, or hostname")
        if re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", text):
            raise ValueError("invalid IPv4 address")
        labels = text.split(".")
        if not labels or any(
            len(label) > 63
            or re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", label) is None
            for label in labels
        ):
            raise ValueError("host must be an IPv4 address, IPv6 address, or hostname")
        return text


class NetworkImportRequest(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_NETWORK_IMPORT_BYTES)
    source: str = Field(default="manual", min_length=1, max_length=128)

    @field_validator("content")
    @classmethod
    def validate_content_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_NETWORK_IMPORT_BYTES:
            raise ValueError(f"content must not exceed {MAX_NETWORK_IMPORT_BYTES} UTF-8 bytes")
        return value


class ApkAnalyzeRequest(BaseModel):
    assessment_id: str = Field(min_length=1, max_length=128, pattern=ASSESSMENT_ID_PATTERN)
    apk_path: str = Field(min_length=1)


class FridaObservation(BaseModel):
    assessment_id: str = Field(min_length=1, max_length=128, pattern=ASSESSMENT_ID_PATTERN)
    package: str = Field(min_length=1, max_length=255)
    script_id: str | None = Field(default=None, max_length=255)
    event_type: str = Field(min_length=1, max_length=128)
    summary: str = Field(min_length=1, max_length=2_000)
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("details")
    @classmethod
    def validate_details_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_FRIDA_DETAILS_BYTES:
            raise ValueError(f"details must not exceed {MAX_FRIDA_DETAILS_BYTES} UTF-8 bytes")
        return _redact_sensitive_data(value)


@app.exception_handler(AndroidCommandError)
def adb_error_handler(_request, exc: AndroidCommandError):
    return JSONResponse(
        status_code=502,
        content={
            "message": str(exc),
            "returncode": exc.returncode,
            "stdout": exc.stdout[-2000:],
            "stderr": exc.stderr[-2000:],
        },
    )


@app.get("/health")
def health():
    payload = state.controller.health()
    payload["mobile_tools"] = tool_status()
    return payload


@app.get("/health/live")
def live():
    return {"ok": True}


@app.get("/health/ready")
def ready():
    payload = state.controller.health()
    boot_completed = state.controller.boot_completed()
    is_ready = payload.get("ok") is True and boot_completed
    payload.update(
        {
            "ready": is_ready,
            "boot_completed": boot_completed,
            "mobile_tools": tool_status(),
        }
    )
    if not is_ready:
        return JSONResponse(status_code=503, content=payload)
    return payload


@app.get("/devices")
def devices():
    return {"devices": state.controller.devices()}


@app.post("/app/install")
def install_app(body: InstallRequest):
    try:
        return state.controller.install_apk(Path(body.apk_path), reinstall=body.reinstall)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/app/start")
def start_app(body: StartAppRequest):
    return state.controller.start_app(body.package, body.activity)


@app.post("/app/stop")
def stop_app(body: PackageRequest):
    return state.controller.stop_app(body.package)


@app.post("/app/clear")
def clear_app_data(body: PackageRequest):
    return state.controller.clear_app_data(body.package)


@app.post("/input/tap")
def tap(body: TapRequest):
    return state.controller.tap(body.x, body.y)


@app.post("/input/swipe")
def swipe(body: SwipeRequest):
    return state.controller.swipe(body.x1, body.y1, body.x2, body.y2, body.duration_ms)


@app.post("/input/text")
def type_text(body: TextRequest):
    return state.controller.type_text(body.text)


@app.post("/input/key")
def press_key(body: KeyRequest):
    return state.controller.press_key(body.key)


@app.post("/input/back")
def press_back():
    return state.controller.press_key("BACK")


@app.post("/input/home")
def press_home():
    return state.controller.press_key("HOME")


@app.get("/observe/screenshot")
def screenshot():
    return state.controller.screenshot_base64()


@app.get("/observe/ui")
def dump_ui():
    return state.controller.dump_ui()


@app.get("/observe/activity")
def current_activity():
    return state.controller.current_activity()


@app.post("/observe/logcat")
def logcat_tail(body: LogcatRequest):
    return state.controller.logcat_tail(body.lines)


@app.get("/network/history")
def network_history(limit: int = 100):
    bounded = max(1, min(limit, 1000))
    with state.network_lock:
        events = list(state.network_events)[-bounded:]
    return {"events": events}


@app.post("/network/events")
def add_network_event(event: NetworkEvent):
    payload = _sanitize_network_event(event.model_dump())
    with state.network_lock:
        event_id = _assign_network_event_id(payload)
        state.network_events.append(payload)
        index = len(state.network_events) - 1
    return {"stored": True, "event_id": event_id, "index": index}


@app.post("/network/import")
def import_network_events(body: NetworkImportRequest):
    try:
        events = parse_network_import(body.content)
        if len(events) > MAX_NETWORK_IMPORT_EVENTS:
            raise ValueError(f"network import accepts at most {MAX_NETWORK_IMPORT_EVENTS} events")
        for event in events:
            event["source"] = body.source
        sanitized = [_sanitize_network_event(event) for event in events]
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with state.network_lock:
        event_ids = [_assign_network_event_id(event) for event in sanitized]
        state.network_events.extend(sanitized)
        total = len(state.network_events)
    return {
        "stored": len(sanitized),
        "total": total,
        "source": body.source,
        "event_ids": event_ids,
    }


@app.post("/network/proxy/set")
def set_network_proxy(body: ProxyRequest):
    return state.controller.set_http_proxy(body.host, body.port)


@app.post("/network/proxy/clear")
def clear_network_proxy():
    return state.controller.clear_http_proxy()


@app.post("/frida/observations")
def add_frida_observation(body: FridaObservation):
    payload = body.model_dump()
    payload["recorded_at"] = datetime.now(UTC).isoformat()
    with state.frida_lock:
        try:
            state.frida_observations.append(body.assessment_id, payload)
        except ValueError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        index = len(state.frida_observations.list(body.assessment_id)) - 1
    return {"stored": True, "index": index}


@app.get("/frida/observations")
def frida_observations(
    assessment_id: str = Query(min_length=1, max_length=128, pattern=ASSESSMENT_ID_PATTERN),
    limit: int = 100,
):
    bounded = max(1, min(limit, 1000))
    with state.frida_lock:
        observations = state.frida_observations.list(assessment_id)
    return {"observations": observations[-bounded:]}


@app.delete("/frida/observations")
def clear_frida_observations(
    assessment_id: str = Query(min_length=1, max_length=128, pattern=ASSESSMENT_ID_PATTERN),
):
    with state.frida_lock:
        removed = state.frida_observations.clear(assessment_id)
    return {"cleared": True, "removed": removed}


@app.post("/reverse/analyze")
def reverse_analyze(body: ApkAnalyzeRequest):
    try:
        apk_path = _resolve_artifact_path(body.apk_path)
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not state.reverse_analysis_slots.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="another reverse analysis is already running")
    try:
        report = analyze_apk(apk_path)
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        state.reverse_analysis_slots.release()
    report["assessment_id"] = body.assessment_id
    with state.reverse_lock:
        try:
            state.reverse_reports.append(body.assessment_id, report)
        except ValueError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
    return report


@app.get("/reverse/reports")
def reverse_reports(
    assessment_id: str = Query(min_length=1, max_length=128, pattern=ASSESSMENT_ID_PATTERN),
    limit: int = 20,
):
    bounded = max(1, min(limit, 100))
    with state.reverse_lock:
        reports = state.reverse_reports.list(assessment_id)
    return {"reports": reports[-bounded:]}


@app.delete("/reverse/reports")
def clear_reverse_reports(
    assessment_id: str = Query(min_length=1, max_length=128, pattern=ASSESSMENT_ID_PATTERN),
):
    with state.reverse_lock:
        removed = state.reverse_reports.clear(assessment_id)
    return {"cleared": True, "removed": removed}


@app.get("/frida/scripts")
def frida_scripts():
    return {"templates": frida_script_templates(), "tools": tool_status()}


@app.get("/lab/profiles")
def labs():
    return {"profiles": lab_profiles()}


@app.delete("/network/history")
def clear_network_history():
    with state.network_lock:
        state.network_events.clear()
    return {"cleared": True}


def _sanitize_network_event(event: dict[str, Any]) -> dict[str, Any]:
    payload = dict(event)
    url = str(payload.get("url") or "")
    if not url or len(url) > MAX_NETWORK_URL_CHARS:
        raise ValueError(f"network event url must contain at most {MAX_NETWORK_URL_CHARS} characters")
    payload["url"] = url
    note = payload.get("note")
    if note is not None and len(str(note)) > MAX_NETWORK_NOTE_CHARS:
        raise ValueError(f"network event note must contain at most {MAX_NETWORK_NOTE_CHARS} characters")
    payload["request_headers"] = _redact_headers(payload.get("request_headers"))
    payload["response_headers"] = _redact_headers(payload.get("response_headers"))
    payload["request_body_preview"] = _bounded_body_preview(payload.get("request_body_preview"))
    payload["response_body_preview"] = _bounded_body_preview(payload.get("response_body_preview"))
    _validate_network_event_size(payload)
    return payload


def _assign_network_event_id(event: dict[str, Any]) -> str:
    event_id = f"net-{state.next_network_event_id:012d}"
    state.next_network_event_id += 1
    event["event_id"] = event_id
    return event_id


def _redact_headers(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    _validate_headers(value)
    redacted: dict[str, str] = {}
    for name, header_value in value.items():
        normalized_name = str(name).strip()
        redacted[normalized_name] = (
            "[REDACTED]" if _is_sensitive_field(normalized_name) else str(header_value)
        )
    return redacted


def _bounded_body_preview(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value
        stripped = text.strip()
        if stripped.startswith(("{", "[")):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                pass
            else:
                if isinstance(parsed, (dict, list)):
                    text = json.dumps(
                        _redact_sensitive_data(parsed),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
    else:
        text = json.dumps(
            _redact_sensitive_data(value),
            ensure_ascii=False,
            separators=(",", ":"),
        )
    return text[:MAX_NETWORK_BODY_PREVIEW]


def _validate_headers(value: dict[str, Any]) -> None:
    if len(value) > MAX_NETWORK_HEADERS:
        raise ValueError(f"network event headers must contain at most {MAX_NETWORK_HEADERS} entries")
    for name, header_value in value.items():
        if len(str(name).strip()) > MAX_NETWORK_HEADER_NAME_CHARS:
            raise ValueError("network event header name is too long")
        if len(str(header_value)) > MAX_NETWORK_HEADER_VALUE_CHARS:
            raise ValueError("network event header value is too long")


def _validate_network_event_size(value: dict[str, Any]) -> None:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_NETWORK_EVENT_BYTES:
        raise ValueError(f"network event exceeds event byte limit of {MAX_NETWORK_EVENT_BYTES}")


def _is_sensitive_field(name: str) -> bool:
    camel_separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", name.strip())
    normalized = camel_separated.casefold().replace("_", "-")
    return normalized in SENSITIVE_FIELD_NAMES or normalized.endswith(
        ("-token", "-api-key", "-password", "-secret")
    )


def _redact_sensitive_data(value: Any, *, depth: int = 0) -> Any:
    if depth >= 32:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]"
                if _is_sensitive_field(str(key))
                else _redact_sensitive_data(item, depth=depth + 1)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive_data(item, depth=depth + 1) for item in value]
    return value


def _resolve_artifact_path(value: str) -> Path:
    if value.startswith(("\\\\", "//")):
        raise ValueError("UNC artifact paths are not allowed")
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = state.artifact_root / candidate
    if candidate.is_symlink():
        raise ValueError("symbolic-link artifact paths are not allowed")
    resolved = candidate.resolve(strict=True)
    root = state.artifact_root.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError(f"apk path must stay inside artifact root: {root}")
    return resolved
