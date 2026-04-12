# API Routes - 路由模块
from .scan import router as scan_router
from .task import router as task_router
from .report import router as report_router
from .prompts import router as prompts_router
from .queue import router as queue_router

__all__ = [
    "scan_router",
    "task_router",
    "report_router",
    "prompts_router",
    "queue_router",
]
