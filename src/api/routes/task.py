"""
Task Routes - 任务管理API路由
"""

import time
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from loguru import logger

from ...core.queue import get_task_queue, TaskStatus as QueueTaskStatus
from ..models.schemas import TaskInfo


router = APIRouter()


class OperationResponse(BaseModel):
    """操作响应"""

    success: bool
    message: str


def _task_to_taskinfo(task: dict) -> TaskInfo:
    """将任务字典转换为 TaskInfo 模型"""
    created_at = (
        datetime.fromisoformat(task["created_at"])
        if task.get("created_at")
        else datetime.now()
    )
    started_at = (
        datetime.fromisoformat(task["started_at"]) if task.get("started_at") else None
    )
    completed_at = (
        datetime.fromisoformat(task["completed_at"])
        if task.get("completed_at")
        else None
    )

    data = task.get("data", {})
    name = data.get("task_type", "unknown")
    description = data.get("target", "") or data.get("scan_id", "")

    return TaskInfo(
        task_id=task.get("task_id", ""),
        name=name,
        description=description,
        status=task.get("status", "pending"),
        priority=str(task.get("priority", "medium")),
        progress=task.get("progress", 0),
        created_at=created_at,
        started_at=started_at,
        completed_at=completed_at,
        error=task.get("last_error"),
    )


@router.get("/", response_model=List[TaskInfo])
async def list_tasks(status: Optional[str] = None):
    """列出所有任务"""
    task_queue = get_task_queue()
    all_tasks = []

    try:
        task_ids = []
        if status == "pending":
            task_ids = task_queue.client.zrange(task_queue.pending_key, 0, -1)
        elif status == "processing":
            task_ids = task_queue.client.hkeys(task_queue.processing_key)
        elif status == "completed":
            task_ids = task_queue.client.hkeys(task_queue.completed_key)
        elif status == "failed":
            task_ids = task_queue.client.hkeys(task_queue.failed_key)
        else:
            task_ids.extend(task_queue.client.zrange(task_queue.pending_key, 0, -1))
            task_ids.extend(task_queue.client.hkeys(task_queue.processing_key))
            task_ids.extend(task_queue.client.hkeys(task_queue.completed_key))
            task_ids.extend(task_queue.client.hkeys(task_queue.failed_key))

        pipe = task_queue.client.pipeline()
        for task_id in task_ids:
            pipe.get(f"pentest:task:{task_id}")
        results = pipe.execute()

        for task_id, data in zip(task_ids, results):
            if data:
                task = task_queue._get_task(task_id)
                if task:
                    all_tasks.append(_task_to_taskinfo(task))

        return all_tasks

    except Exception as e:
        logger.error(f"Failed to list tasks: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{task_id}", response_model=TaskInfo)
async def get_task(task_id: str):
    """获取任务详情"""
    task_queue = get_task_queue()
    task = task_queue.get_status(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return _task_to_taskinfo(task)


@router.post("/{task_id}/cancel", response_model=OperationResponse)
async def cancel_task(task_id: str):
    """取消任务"""
    task_queue = get_task_queue()
    task = task_queue.get_status(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    current_status = task.get("status")
    if current_status in [
        QueueTaskStatus.COMPLETED.value,
        QueueTaskStatus.FAILED.value,
    ]:
        raise HTTPException(
            status_code=400, detail=f"Cannot cancel task in status: {current_status}"
        )

    task["status"] = QueueTaskStatus.FAILED.value
    task["last_error"] = "Cancelled by user"
    task["cancelled_at"] = datetime.now().isoformat()
    task_queue._save_task(task_id, task)

    task_queue.client.hdel(task_queue.processing_key, task_id)
    task_queue.client.zrem(task_queue.pending_key, task_id)

    logger.info(f"Task cancelled: {task_id}")
    return OperationResponse(success=True, message="Task cancelled successfully")


@router.post("/{task_id}/retry", response_model=OperationResponse)
async def retry_task(task_id: str):
    """重试失败的任务"""
    task_queue = get_task_queue()
    task = task_queue.get_status(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    current_status = task.get("status")
    if current_status != QueueTaskStatus.FAILED.value:
        raise HTTPException(status_code=400, detail="Only failed tasks can be retried")

    task["status"] = QueueTaskStatus.PENDING.value
    task["retries"] = 0
    task_queue._save_task(task_id, task)

    task_queue.client.hdel(task_queue.failed_key, task_id)

    task_data = task.get("data", {})
    task_data["task_id"] = task_id
    priority = task.get("priority", 0)
    task_queue.enqueue(task_data, priority=priority)

    logger.info(f"Task retried: {task_id}")
    return OperationResponse(success=True, message="Task requeued successfully")


@router.get("/{task_id}/logs")
async def get_task_logs(task_id: str):
    """获取任务执行日志"""
    task_queue = get_task_queue()
    task = task_queue.get_status(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    logs = {
        "task_id": task_id,
        "created_at": task.get("created_at"),
        "started_at": task.get("started_at"),
        "completed_at": task.get("completed_at"),
        "last_error": task.get("last_error"),
        "retries": task.get("retries", 0),
    }

    return logs
