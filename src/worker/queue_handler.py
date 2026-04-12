"""
Queue Handler - 队列处理器
使用 TaskQueue 重构，异步非阻塞消费
"""

import asyncio
from typing import Optional
from loguru import logger

from ..core.queue import TaskQueue, get_task_queue
from .task_executor import TaskExecutor


class QueueHandler:
    """队列处理器（异步消费）"""

    def __init__(
        self,
        task_queue: Optional[TaskQueue] = None,
        task_executor: Optional[TaskExecutor] = None,
    ):
        self.task_queue = task_queue or get_task_queue()
        self.task_executor = task_executor or TaskExecutor()
        self.running = False
        # 从 TaskQueue 获取默认超时配置
        self.dequeue_timeout = task_queue.task_timeout if task_queue else 5

    async def start_consuming(self):
        """开始消费任务（非阻塞）"""
        self.running = True
        logger.info("Starting to consume tasks...")

        while self.running:
            try:
                # 将同步阻塞的 dequeue 放入线程池执行，避免阻塞事件循环
                task = await asyncio.to_thread(
                    self.task_queue.dequeue, block=True, timeout=self.dequeue_timeout
                )

                if task:
                    # 异步处理任务（不等待完成，继续取下一个）
                    asyncio.create_task(self._process_task(task))

            except Exception as e:
                logger.error(f"Error consuming task: {e}")
                await asyncio.sleep(1)

    async def _process_task(self, task: dict):
        """处理单个任务"""
        task_id = task.get("task_id", "unknown")
        try:
            # 执行任务
            result = await self.task_executor.execute_task(task)

            # 标记完成（同步 I/O，放入线程池）
            await asyncio.to_thread(self.task_queue.complete, task_id, result)
            logger.info(f"Task completed: {task_id}")

        except Exception as e:
            # 标记失败（同步 I/O，放入线程池）
            await asyncio.to_thread(self.task_queue.fail, task_id, str(e))
            logger.error(f"Task failed: {task_id} - {e}")

    def stop_consuming(self):
        """停止消费"""
        self.running = False
        logger.info("Stopped consuming from queue")
