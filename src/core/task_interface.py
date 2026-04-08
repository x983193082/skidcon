"""
Task Interface - 任务抽象基类
定义渗透测试任务的标准接口
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class TaskPriority(Enum):
    """任务优先级"""
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskResult:
    """任务执行结果"""
    task_id: str
    success: bool
    data: Dict[str, Any]
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    execution_time: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "execution_time": self.execution_time
        }


@dataclass
class TaskContext:
    """任务执行上下文"""
    target: str
    scope: List[str] = field(default_factory=list)
    constraints: Dict[str, Any] = field(default_factory=dict)
    previous_results: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseTask(ABC):
    """
    任务抽象基类
    
    定义渗透测试任务的标准生命周期：
    1. prepare - 任务准备
    2. execute - 任务执行
    3. validate - 结果验证
    4. cleanup - 清理工作
    """
    
    def __init__(
        self,
        task_id: str,
        name: str,
        description: str = "",
        priority: TaskPriority = TaskPriority.MEDIUM,
        dependencies: List[str] = None,
        timeout: int = 300  # 秒
    ):
        self.task_id = task_id
        self.name = name
        self.description = description
        self.priority = priority
        self.dependencies = dependencies or []
        self.timeout = timeout
        self.status = TaskStatus.PENDING
        self._result: Optional[TaskResult] = None
        self._context: Optional[TaskContext] = None
    
    @abstractmethod
    async def prepare(self, context: TaskContext) -> bool:
        """
        任务准备阶段
        
        Args:
            context: 任务上下文
        
        Returns:
            准备是否成功
        """
        pass
    
    @abstractmethod
    async def execute(self) -> TaskResult:
        """
        任务执行阶段
        
        Returns:
            任务执行结果
        """
        pass
    
    @abstractmethod
    async def validate(self, result: TaskResult) -> bool:
        """
        结果验证阶段
        
        Args:
            result: 执行结果
        
        Returns:
            结果是否有效
        """
        pass
    
    @abstractmethod
    async def cleanup(self) -> None:
        """
        清理阶段 - 释放资源、清理临时文件等
        """
        pass
    
    def set_context(self, context: TaskContext) -> None:
        """设置任务上下文"""
        self._context = context
    
    def get_result(self) -> Optional[TaskResult]:
        """获取任务结果"""
        return self._result
    
    def update_status(self, status: TaskStatus) -> None:
        """更新任务状态"""
        self.status = status
    
    def is_ready(self, completed_tasks: List[str]) -> bool:
        """
        检查任务是否就绪（依赖是否满足）
        
        Args:
            completed_tasks: 已完成的任务ID列表
        
        Returns:
            任务是否可以执行
        """
        return all(dep in completed_tasks for dep in self.dependencies)
    
    async def run(self, context: TaskContext) -> TaskResult:
        """
        完整的任务执行流程
        
        Args:
            context: 任务上下文
        
        Returns:
            任务结果
        """
        started_at = datetime.now()
        self._context = context
        
        try:
            self.status = TaskStatus.RUNNING
            
            # 准备阶段
            if not await self.prepare(context):
                raise RuntimeError("Task preparation failed")
            
            # 执行阶段
            result = await self.execute()
            
            # 验证阶段
            if not await self.validate(result):
                result.success = False
                result.error = "Result validation failed"
            
            result.started_at = started_at
            result.completed_at = datetime.now()
            result.execution_time = (result.completed_at - started_at).total_seconds()
            
            self._result = result
            self.status = TaskStatus.COMPLETED if result.success else TaskStatus.FAILED
            
            return result
            
        except Exception as e:
            self.status = TaskStatus.FAILED
            self._result = TaskResult(
                task_id=self.task_id,
                success=False,
                data={},
                error=str(e),
                started_at=started_at,
                completed_at=datetime.now()
            )
            return self._result
            
        finally:
            await self.cleanup()
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id='{self.task_id}' name='{self.name}' status={self.status.value}>"
