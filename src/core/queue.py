"""
Task Queue - Redis 任务队列
支持入队/出队、状态管理、超时重试、优先级队列
"""

import json
import threading
import time
import uuid
from enum import Enum
from typing import Any, Dict, Optional
from datetime import datetime, timedelta
import redis
from loguru import logger
from .settings import get_settings


class TaskStatus(Enum):
    """任务状态枚举"""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


class TaskQueue:
    """Redis 任务队列（线程安全单例）"""

    _instance: Optional["TaskQueue"] = None
    _lock = threading.Lock()

    def __init__(self, redis_url: Optional[str] = None):
        settings = get_settings()
        self.redis_url = redis_url or settings.redis_url
        self.client: Optional[redis.Redis] = None

        # 从配置读取队列参数
        self.task_ttl = settings.queue_task_ttl
        self.task_timeout = settings.queue_task_timeout
        self.max_retries = settings.queue_max_retries
        self.retry_delays = settings.queue_retry_delays
        self.dead_letter_ttl = settings.queue_dead_letter_ttl

        # 队列键名
        self.pending_key = "pentest:tasks:pending"
        self.processing_key = "pentest:tasks:processing"
        self.completed_key = "pentest:tasks:completed"
        self.failed_key = "pentest:tasks:failed"
        self.dead_letter_key = "pentest:tasks:dead_letter"

        self._connect()

    @classmethod
    def get_instance(cls, redis_url: Optional[str] = None) -> "TaskQueue":
        """获取单例（线程安全）"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(redis_url)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（用于测试）"""
        with cls._lock:
            cls._instance = None

    def _connect(self) -> None:
        """连接 Redis"""
        try:
            self.client = redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_keepalive=True,
                health_check_interval=30,
            )
            self.client.ping()
            logger.info(f"Connected to Redis: {self.redis_url}")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self.client = None
            raise

    def _ensure_connection(self) -> None:
        """确保连接有效，否则重连"""
        if self.client is None:
            self._connect()
            return
        try:
            self.client.ping()
        except (redis.ConnectionError, redis.TimeoutError, redis.RedisError):
            logger.warning("Redis connection lost, reconnecting...")
            self._connect()

    def _generate_task_id(self) -> str:
        """生成任务 ID"""
        return f"task_{uuid.uuid4().hex[:12]}"

    def enqueue(self, task_data: Dict[str, Any], priority: int = 0) -> str:
        """
        入队（使用有序集合支持优先级）

        Args:
            task_data: 任务数据
            priority: 优先级（非负整数，值越大优先级越高，默认 0）

        Returns:
            task_id
        """
        self._ensure_connection()
        task_id = task_data.get("task_id") or self._generate_task_id()
        task = {
            "task_id": task_id,
            "status": TaskStatus.PENDING.value,
            "data": task_data,
            "created_at": datetime.now().isoformat(),
            "retries": 0,
            "priority": priority,
        }
        try:
            # 存储任务详情
            key = f"pentest:task:{task_id}"
            self.client.setex(key, self.task_ttl, json.dumps(task))
            # 计算 score：优先级主导 + 时间戳保证顺序
            # 使用优先级 + 时间戳组合：score = 优先级 * 1e12 + timestamp
            # 优先级越大 score 越大，越先出队
            score = priority * 1e12 + time.time()
            self.client.zadd(self.pending_key, {task_id: score})
            logger.info(f"Task enqueued: {task_id} (priority={priority})")
        except Exception as e:
            logger.error(f"Failed to enqueue task: {e}")
            raise
        return task_id

    def dequeue(self, block: bool = True, timeout: int = 5) -> Optional[Dict]:
        """
        出队（从有序集合中取出 score 最小的任务）

        Args:
            block: 是否阻塞
            timeout: 阻塞超时（秒）

        Returns:
            任务数据或 None
        """
        self._ensure_connection()
        try:
            if block:
                # BZPOPMIN 返回: (key, member, score) 元组
                # 例如: (b'pentest:tasks:pending', b'task_abc123', 1.0)
                result = self.client.bzpopmin(self.pending_key, timeout=timeout)
                if not result:
                    return None
                # 解包三个值
                _, task_id, _ = result
                task_id = str(task_id)
            else:
                result = self.client.zpopmin(self.pending_key, count=1)
                if not result:
                    return None
                task_id = str(result[0][0])
            task = self._get_task(task_id)
            if not task:
                logger.error(f"Task detail lost for id: {task_id}")
                self._add_to_dead_letter(task_id, "Detail missing at dequeue")
                return None
            # 更新状态为处理中
            task["status"] = TaskStatus.PROCESSING.value
            task["started_at"] = datetime.now().isoformat()
            self._save_task(task_id, task)
            # 移到 processing 哈希
            self.client.hset(self.processing_key, task_id, json.dumps(task))
            return task
        except Exception as e:
            logger.error(f"Failed to dequeue task: {e}")
            return None

    def _get_task(self, task_id: str) -> Optional[Dict]:
        """获取任务详情"""
        try:
            key = f"pentest:task:{task_id}"
            data = self.client.get(key)
            return json.loads(data) if data else None
        except Exception as e:
            logger.error(f"Failed to get task {task_id}: {e}")
            return None

    def _save_task(self, task_id: str, task: Dict) -> None:
        """保存任务详情"""
        try:
            key = f"pentest:task:{task_id}"
            self.client.setex(key, self.task_ttl, json.dumps(task))
        except Exception as e:
            logger.error(f"Failed to save task {task_id}: {e}")

    def _add_to_dead_letter(self, task_id: str, reason: str) -> None:
        """将任务加入死信队列（带过期时间）"""
        try:
            dead_letter_item = json.dumps(
                {
                    "task_id": task_id,
                    "reason": reason,
                    "timestamp": datetime.now().isoformat(),
                }
            )
            # 使用 HSET + EXPIRE 确保死信有 TTL
            self.client.hset(self.dead_letter_key, task_id, dead_letter_item)
            self.client.expire(self.dead_letter_key, self.dead_letter_ttl)
        except Exception as e:
            logger.error(f"Failed to add {task_id} to dead letter: {e}")

    def get_status(self, task_id: str) -> Optional[Dict]:
        """获取任务状态"""
        self._ensure_connection()
        return self._get_task(task_id)

    def complete(self, task_id: str, result: Dict[str, Any]) -> None:
        """标记任务完成"""
        self._ensure_connection()
        try:
            task = self._get_task(task_id)
            if not task:
                logger.warning(f"Task not found when completing: {task_id}")
                return
            task["status"] = TaskStatus.COMPLETED.value
            task["completed_at"] = datetime.now().isoformat()
            task["result"] = result
            self._save_task(task_id, task)
            self.client.hdel(self.processing_key, task_id)
            self.client.hset(self.completed_key, task_id, json.dumps(task))
            logger.info(f"Task completed: {task_id}")
        except Exception as e:
            logger.error(f"Failed to complete task {task_id}: {e}")

    def fail(self, task_id: str, error: str) -> None:
        """标记任务失败并处理重试"""
        self._ensure_connection()
        try:
            task = self._get_task(task_id)
            if not task:
                logger.warning(f"Task not found when failing: {task_id}")
                return
            # 从 processing 中移除
            self.client.hdel(self.processing_key, task_id)
            task["retries"] = task.get("retries", 0) + 1
            task["last_error"] = error
            # 计算重试索引（修正逻辑）
            retry_count = task["retries"]
            if retry_count >= self.max_retries:
                # 超过最大重试次数
                task["status"] = TaskStatus.FAILED.value
                task["failed_at"] = datetime.now().isoformat()
                self._save_task(task_id, task)
                self.client.hset(self.failed_key, task_id, json.dumps(task))
                logger.error(f"Task failed permanently: {task_id} (max retries)")
            else:
                # 加入重试队列
                task["status"] = TaskStatus.PENDING.value
                # 修正索引：当 retries=1 时取 retry_delays[0]=10
                idx = min(retry_count - 1, len(self.retry_delays) - 1)
                retry_delay = self.retry_delays[idx]
                task["retry_at"] = (
                    datetime.now() + timedelta(seconds=retry_delay)
                ).isoformat()
                self._save_task(task_id, task)
                # 重新入队（保持原优先级）
                priority = task.get("priority", 0)
                score = priority * 1e12 + time.time()
                self.client.zadd(self.pending_key, {task_id: score})
                logger.warning(
                    f"Task scheduled for retry: {task_id} "
                    f"(attempt {retry_count}/{self.max_retries}, delay {retry_delay}s)"
                )
        except Exception as e:
            logger.error(f"Failed to mark task {task_id} as failed: {e}")

    def check_timeouts(self) -> int:
        """检查超时任务"""
        self._ensure_connection()
        count = 0
        try:
            for task_id, task_data in self.client.hgetall(self.processing_key).items():
                task = json.loads(task_data)
                started_at = task.get("started_at")
                if not started_at:
                    continue
                started_time = datetime.fromisoformat(started_at)
                if datetime.now() - started_time > timedelta(seconds=self.task_timeout):
                    logger.warning(f"Task timeout detected: {task_id}")
                    self.fail(task_id, "Task execution timeout")
                    count += 1
        except Exception as e:
            logger.error(f"Failed to check timeouts: {e}")
        return count

    def retry_failed(self) -> int:
        """手动重试所有失败任务"""
        self._ensure_connection()
        count = 0
        try:
            for task_id, task_data in self.client.hgetall(self.failed_key).items():
                task = json.loads(task_data)
                task["status"] = TaskStatus.PENDING.value
                task["retries"] = 0
                self._save_task(task_id, task)
                self.client.hdel(self.failed_key, task_id)
                priority = task.get("priority", 0)
                score = priority * 1e12 + time.time()
                self.client.zadd(self.pending_key, {task_id: score})
                count += 1
                logger.info(f"Manually retrying failed task: {task_id}")
        except Exception as e:
            logger.error(f"Failed to retry failed tasks: {e}")
        return count

    def get_stats(self) -> Dict[str, int]:
        """获取队列统计"""
        self._ensure_connection()
        try:
            return {
                "pending": self.client.zcard(self.pending_key),
                "processing": self.client.hlen(self.processing_key),
                "completed": self.client.hlen(self.completed_key),
                "failed": self.client.hlen(self.failed_key),
                "dead_letter": self.client.hlen(self.dead_letter_key),
            }
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {
                "pending": 0,
                "processing": 0,
                "completed": 0,
                "failed": 0,
                "dead_letter": 0,
            }


def get_task_queue(redis_url: Optional[str] = None) -> TaskQueue:
    """获取任务队列单例（便捷函数）"""
    return TaskQueue.get_instance(redis_url)
