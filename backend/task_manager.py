"""
SkidCon 并发任务管理模块
维护任务队列，控制最大并发数，跟踪任务状态
"""

import asyncio
import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Callable
from pathlib import Path
from config import MAX_CONCURRENT_TASKS, TASKS_DIR


class TaskStatus:
    """任务状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Task:
    """任务类"""
    
    def __init__(self, target: str, task_id: Optional[str] = None):
        self.id = task_id or str(uuid.uuid4())
        self.target = target
        self.status = TaskStatus.PENDING
        self.created_at = datetime.now().isoformat()
        self.started_at = None
        self.completed_at = None
        self.result = None
        self.error = None
        self.logs = []
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "target": self.target,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "result": self.result,
            "error": self.error,
            "logs": self.logs[-50:]  # 只保留最近 50 条日志
        }
    
    def save(self):
        """保存任务到文件"""
        task_file = TASKS_DIR / f"{self.id}.json"
        with open(task_file, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
    
    def add_log(self, message: str):
        """添加日志"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.logs.append(f"[{timestamp}] {message}")
        self.save()


class TaskManager:
    """任务管理器"""
    
    def __init__(self, max_concurrent: int = MAX_CONCURRENT_TASKS):
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.tasks: Dict[str, Task] = {}
        self.task_queue = asyncio.Queue()
        self.websocket_clients: Dict[str, List] = {}  # task_id -> [websocket_connections]
    
    def create_task(self, target: str) -> Task:
        """创建新任务"""
        task = Task(target=target)
        self.tasks[task.id] = task
        task.save()
        return task
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务"""
        return self.tasks.get(task_id)
    
    def get_all_tasks(self) -> List[Dict]:
        """获取所有任务"""
        return [task.to_dict() for task in self.tasks.values()]
    
    def load_tasks_from_disk(self):
        """从磁盘加载任务"""
        for task_file in TASKS_DIR.glob("*.json"):
            try:
                with open(task_file, "r", encoding="utf-8") as f:
                    task_data = json.load(f)
                
                task = Task(
                    target=task_data["target"],
                    task_id=task_data["id"]
                )
                task.status = task_data["status"]
                task.created_at = task_data["created_at"]
                task.started_at = task_data.get("started_at")
                task.completed_at = task_data.get("completed_at")
                task.result = task_data.get("result")
                task.error = task_data.get("error")
                task.logs = task_data.get("logs", [])
                
                self.tasks[task.id] = task
            except Exception as e:
                print(f"加载任务文件 {task_file} 失败: {e}")
    
    async def execute_task(self, task: Task, executor_func: Callable, callback: Optional[Callable] = None):
        """执行任务（带并发控制）"""
        async with self.semaphore:
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now().isoformat()
            task.save()
            
            # 创建回调函数，同时更新任务日志和推送 WebSocket
            async def combined_callback(message: str):
                task.add_log(message)
                
                # 推送 WebSocket 消息
                if task.id in self.websocket_clients:
                    clients_to_remove = []
                    for client in self.websocket_clients[task.id]:
                        try:
                            await client.send_json({
                                "type": "log",
                                "task_id": task.id,
                                "message": message
                            })
                        except Exception:
                            clients_to_remove.append(client)
                    
                    # 移除断开的连接
                    for client in clients_to_remove:
                        self.websocket_clients[task.id].remove(client)
                
                # 调用原始回调
                if callback:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(message)
                    else:
                        callback(message)
            
            try:
                # 执行任务
                result = await executor_func(task.target, combined_callback)
                
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.now().isoformat()
                task.result = result
                task.save()
                
                # 发送完成消息
                if task.id in self.websocket_clients:
                    for client in self.websocket_clients[task.id]:
                        try:
                            await client.send_json({
                                "type": "completed",
                                "task_id": task.id,
                                "result": result
                            })
                        except Exception:
                            pass
                
            except Exception as e:
                task.status = TaskStatus.FAILED
                task.completed_at = datetime.now().isoformat()
                task.error = str(e)
                task.save()
                
                # 发送错误消息
                if task.id in self.websocket_clients:
                    for client in self.websocket_clients[task.id]:
                        try:
                            await client.send_json({
                                "type": "failed",
                                "task_id": task.id,
                                "error": str(e)
                            })
                        except Exception:
                            pass
    
    def register_websocket(self, task_id: str, websocket):
        """注册 WebSocket 客户端"""
        if task_id not in self.websocket_clients:
            self.websocket_clients[task_id] = []
        self.websocket_clients[task_id].append(websocket)
    
    def unregister_websocket(self, task_id: str, websocket):
        """注销 WebSocket 客户端"""
        if task_id in self.websocket_clients:
            try:
                self.websocket_clients[task_id].remove(websocket)
            except ValueError:
                pass


# 全局任务管理器实例
task_manager = TaskManager()
