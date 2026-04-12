"""
Queue API - 任务队列 API 路由
"""

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, Optional

from ...core.queue import get_task_queue, TaskStatus

router = APIRouter(prefix="/queue", tags=["queue"])


class EnqueueRequest(BaseModel):
    """入队请求"""

    task_data: Dict[str, Any]
    priority: int = 0


class EnqueueResponse(BaseModel):
    """入队响应"""

    task_id: str
    status: str = "pending"


class TaskStatusResponse(BaseModel):
    """任务状态响应"""

    task_id: str
    status: str
    data: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    retries: int = 0


class QueueStatsResponse(BaseModel):
    """队列统计响应"""

    pending: int
    processing: int
    completed: int
    failed: int
    dead_letter: int


@router.post("/enqueue", response_model=EnqueueResponse)
async def enqueue_task(request: EnqueueRequest):
    """入队"""
    try:
        queue = get_task_queue()
        task_id = queue.enqueue(request.task_data, request.priority)
        return EnqueueResponse(task_id=task_id, status="pending")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """获取任务状态"""
    queue = get_task_queue()
    task = queue.get_status(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return TaskStatusResponse(
        task_id=task["task_id"],
        status=task["status"],
        data=task.get("data"),
        created_at=task.get("created_at"),
        started_at=task.get("started_at"),
        completed_at=task.get("completed_at"),
        retries=task.get("retries", 0),
    )


@router.get("/stats", response_model=QueueStatsResponse)
async def get_queue_stats():
    """获取队列统计"""
    queue = get_task_queue()
    stats = queue.get_stats()
    return QueueStatsResponse(**stats)


@router.post("/retry-failed")
async def retry_failed_tasks(background_tasks: BackgroundTasks):
    """重试失败任务（后台执行）"""
    queue = get_task_queue()
    background_tasks.add_task(queue.retry_failed)
    return {"message": "Retry of failed tasks started in background"}


@router.post("/check-timeouts")
async def check_task_timeouts(background_tasks: BackgroundTasks):
    """检查超时任务（后台执行）"""
    queue = get_task_queue()
    background_tasks.add_task(queue.check_timeouts)
    return {"message": "Timeout check started in background"}
