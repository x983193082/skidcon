from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from skidc.android_mcp.adb import AdbController, AndroidCommandError


class AndroidMcpState:
    def __init__(self) -> None:
        self.controller = AdbController()
        self.network_events: list[dict[str, Any]] = []


state = AndroidMcpState()

app = FastAPI(
    title="Skidc Android MCP Bridge",
    description="Minimal Android emulator/app control bridge for authorized mobile testing",
    version="0.1.0",
)


def configure(*, adb_path: str = "adb", device_id: str | None = None, timeout: int = 20) -> None:
    state.controller = AdbController(adb_path=adb_path, device_id=device_id, timeout=timeout)


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
    method: str | None = None
    url: str
    status_code: int | None = None
    request_headers: dict[str, str] = Field(default_factory=dict)
    response_headers: dict[str, str] = Field(default_factory=dict)
    request_body_preview: str | None = None
    response_body_preview: str | None = None
    note: str | None = None


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
    return state.controller.health()


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
    return {"events": state.network_events[-bounded:]}


@app.post("/network/events")
def add_network_event(event: NetworkEvent):
    payload = event.model_dump()
    state.network_events.append(payload)
    return {"stored": True, "index": len(state.network_events) - 1}


@app.delete("/network/history")
def clear_network_history():
    state.network_events.clear()
    return {"cleared": True}
