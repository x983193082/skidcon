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
from loguru import logger

from .routes import scan, task, report, prompts
from .models import schemas
from .routes import history


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("Starting Pentest Crew API...")
    
    # 验证配置
    try:
        from ..core.settings import get_settings
        settings = get_settings()
        logger.info(f"Configuration loaded: provider={settings.llm_provider}")
        
        # 检查 API Key 是否配置
        if settings.llm_provider == "openrouter" and not settings.openrouter_api_key:
            logger.warning("OPENROUTER_API_KEY not configured - LLM features will be limited")
        elif settings.llm_provider == "openai" and not settings.openai_api_key:
            logger.warning("OPENAI_API_KEY not configured - LLM features will be limited")
    except Exception as e:
        logger.error(f"Configuration validation failed: {e}")
    
    # 初始化数据库
    from ..database import Database
    db = Database.get_instance()
    db.create_tables()
    logger.info("Database tables created")
    
    # 初始化向量存储
    try:
        from ..core.knowledge_tools import get_knowledge_tools
        knowledge_tools = get_knowledge_tools()
        await knowledge_tools.initialize_vector_store()
        logger.info("Vector store initialized")
    except Exception as e:
        logger.warning(f"Vector store initialization skipped: {e}")

    yield
    
    logger.info("Shutting down Pentest Crew API...")


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
app.include_router(prompts.router, prefix="/api/v1/prompts", tags=["Prompts"])
app.include_router(history.router, prefix="/api/v1/history", tags=["History"])

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
    logger.info(f"WebSocket connected for task: {task_id}")

    try:
        # 接收初始配置消息
        try:
            data = await asyncio.wait_for(websocket.receive_json(), timeout=30.0)
        except asyncio.TimeoutError:
            await manager.send_message(
                task_id, {"type": "error", "error": "Connection timeout - no configuration received"}
            )
            return
        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected before receiving config: {task_id}")
            return

        target = data.get("target")
        scope = data.get("scope", [])

        if not target:
            await manager.send_message(
                task_id, {"type": "error", "error": "Missing target"}
            )
            return

        logger.info(f"Starting pentest for target: {target}, task_id: {task_id}")

        from ..orchestration.crew_factory import get_crew_factory
        from ..core.crewai_adapter import get_crewai_adapter

        try:
            factory = get_crew_factory()
            crew = factory.create_pentest_crew(target, scope)
        except Exception as e:
            logger.error(f"Failed to create crew: {e}")
            await manager.send_message(
                task_id, {"type": "error", "error": f"Failed to initialize crew: {str(e)}"}
            )
            return

        async def stream_handler(event_type: str, data: Dict):
            try:
                await manager.send_message(task_id, {"type": event_type, "data": data})
            except Exception as e:
                logger.warning(f"Failed to send stream message: {e}")

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
                logger.info(f"Pentest completed for task: {task_id}")
            except Exception as e:
                logger.error(f"Pentest failed for task {task_id}: {e}")
                await manager.send_message(task_id, {"type": "error", "error": str(e)})
            finally:
                manager.disconnect(task_id)

        # 创建后台任务执行渗透测试
        task = asyncio.create_task(run_pentest())

        # 保持连接，等待任务完成或客户端断开
        while task_id in manager.active_connections:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
            except asyncio.TimeoutError:
                # 检查后台任务是否完成
                if task.done():
                    break
                continue
            except WebSocketDisconnect:
                logger.info(f"WebSocket disconnected by client: {task_id}")
                break

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {task_id}")
    except Exception as e:
        logger.error(f"WebSocket error for task {task_id}: {e}")
        try:
            await manager.send_message(task_id, {"type": "error", "error": str(e)})
        except Exception:
            pass
    finally:
        manager.disconnect(task_id)
        logger.info(f"WebSocket cleanup completed for task: {task_id}")


def run_server(host: str = "0.0.0.0", port: int = 8000):
    """启动API服务器"""
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
