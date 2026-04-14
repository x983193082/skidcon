"""
Task Repository - 任务数据访问层
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from ..db_models import Task, TaskHistory, Scan
from .base import BaseRepository
class TaskRepository(BaseRepository[Task]):
    """任务 Repository"""
    def __init__(self, session: Session):
        super().__init__(Task, session)
    def create_task(
        self,
        task_id: str,
        task_type: str,
        scan_id: Optional[str] = None,   # 业务标识 Scan.scan_id
        priority: int = 0,
        **kwargs
    ) -> Task:
        """创建任务记录"""
        # 若提供了 scan_id（业务标识），需转换为内部主键
        internal_scan_id = None
        if scan_id:
            scan = self.session.query(Scan).filter(Scan.scan_id == scan_id).first()
            if not scan:
                raise ValueError(f"Scan with scan_id '{scan_id}' not found")
            internal_scan_id = scan.id
        return self.create(
            task_id=task_id,
            task_type=task_type,
            scan_id=internal_scan_id,   # 存储内部主键
            priority=priority,
            status="pending",
            **kwargs
        )
    def get_by_task_id(self, task_id: str) -> Optional[Task]:
        """通过业务 task_id 获取"""
        return self.get_by_field("task_id", task_id)
    def update_status(
        self,
        task_id: str,
        status: str,
        error: Optional[str] = None,
        result_data: Optional[Dict] = None,
    ) -> Optional[Task]:
        """更新任务状态"""
        task = self.get_by_task_id(task_id)
        if not task:
            return None
        # 记录历史（传入旧状态）
        self._add_history(task, status, notes=f"Changed from {task.status} to {status}")
        task.status = status
        if error is not None:
            task.error = error
        if result_data is not None:
            task.result_data = result_data
        if status == "running" and task.started_at is None:
            task.started_at = datetime.now()
        if status in ("completed", "failed"):
            task.completed_at = datetime.now()
        self.session.flush()
        return task
    def _add_history(
        self,
        task: Task,                  # 传入 Task 对象以获取内部主键
        status: str,
        changed_by: Optional[str] = None,
        notes: Optional[str] = None
    ) -> TaskHistory:
        """添加任务历史记录"""
        history = TaskHistory(
            task_id=task.id,         # ✅ 使用内部主键 tasks.id
            status=status,
            changed_by=changed_by,
            notes=notes,
            changed_at=datetime.now()
        )
        self.session.add(history)
        return history
    def list_by_scan(self, scan_id: str) -> List[Task]:
        """获取扫描的所有任务（通过业务 scan_id）"""
        return self.session.query(Task).join(Scan).filter(
            Scan.scan_id == scan_id
        ).order_by(Task.created_at.desc()).all()
    def list_by_status(self, status: str, limit: int = 100) -> List[Task]:
        """按状态列表"""
        return self.session.query(Task).filter(
            Task.status == status
        ).order_by(Task.created_at.desc()).limit(limit).all()
    def get_history(self, task_id: str) -> List[TaskHistory]:
        """获取任务历史（通过业务 task_id）"""
        # 先获取 Task 内部 ID，再查询历史
        task = self.get_by_task_id(task_id)
        if not task:
            return []
        return self.session.query(TaskHistory).filter(
            TaskHistory.task_id == task.id
        ).order_by(TaskHistory.changed_at.desc()).all()