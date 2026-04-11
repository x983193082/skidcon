"""
FastAPI Main Entry - API服务入口
"""

import json
import asyncio
import threading
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn

from .routes import scan, task, report
from .models import schemas


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    print("Starting Pentest Crew API...")
    yield
    print("Shutting down Pentest Crew API...")


app = FastAPI(
    title="Pentest Crew API",
    description="渗透测试自动化平台API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scan.router, prefix="/api/v1/scan", tags=["Scan"])
app.include_router(task.router, prefix="/api/v1/task", tags=["Task"])
app.include_router(report.router, prefix="/api/v1/report", tags=["Report"])


@app.get("/")
async def root():
    return {"message": "Pentest Crew API", "version": "1.0.0", "docs": "/docs"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


class ConnectionManager:
    """WebSocket 连接管理"""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self._lock = threading.Lock()

    async def connect(self, task_id: str, websocket: WebSocket):
        await websocket.accept()
        with self._lock:
            if task_id in self.active_connections:
                old_ws = self.active_connections[task_id]
                try:
                    await old_ws.close()
                except:
                    pass
            self.active_connections[task_id] = websocket

    def disconnect(self, task_id: str):
        with self._lock:
            self.active_connections.pop(task_id, None)

    async def send_message(self, task_id: str, message: Dict):
        with self._lock:
            ws = self.active_connections.get(task_id)
        if ws:
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(task_id)


manager = ConnectionManager()


@app.websocket("/ws/pentest/{task_id}")
async def pentest_websocket(websocket: WebSocket, task_id: str):
    await manager.connect(task_id, websocket)

    try:
        data = await websocket.receive_json()
        target = data.get("target")
        scope = data.get("scope", [])

        if not target:
            await manager.send_message(
                task_id, {"type": "error", "error": "Missing target"}
            )
            return

        from ..orchestration.crew_factory import get_crew_factory
        from ..core.crewai_adapter import get_crewai_adapter

        factory = get_crew_factory()
        crew = factory.create_pentest_crew(target, scope)

        async def stream_handler(event_type: str, data: Dict):
            await manager.send_message(task_id, {"type": event_type, "data": data})

        async def run_pentest():
            try:
                adapter = get_crewai_adapter()
                result = await adapter.run_crew(
                    crew=crew,
                    inputs={"target": target},
                    stream_handler=stream_handler,
                    task_store=None,
                    task_id=task_id,
                )
                await manager.send_message(
                    task_id,
                    {
                        "type": "complete",
                        "result": result.raw if hasattr(result, "raw") else str(result),
                    },
                )
            except Exception as e:
                await manager.send_message(task_id, {"type": "error", "error": str(e)})
            finally:
                manager.disconnect(task_id)

        asyncio.create_task(run_pentest())

        while task_id in manager.active_connections:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        await manager.send_message(task_id, {"type": "error", "error": str(e)})
    finally:
        manager.disconnect(task_id)


def run_server(host: str = "0.0.0.0", port: int = 8000):
    """启动API服务器"""
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
