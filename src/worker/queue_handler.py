"""
Queue Handler - 队列处理器
负责从 Redis 队列消费任务并分发
"""
import json
import asyncio
from typing import Optional
from loguru import logger


class QueueHandler:
    """队列处理器"""

    def __init__(self, redis_client, task_executor):
        self.redis_client = redis_client
        self.task_executor = task_executor
        self.queue_name = "pentest:tasks:pending"
        self.processing_queue = "pentest:tasks:processing"
        self.running = False

    async def start_consuming(self):
        """开始消费任务"""
        self.running = True
        logger.info(f"Starting to consume from queue: {self.queue_name}")

        while self.running:
            try:
                # 从队列取任务（阻塞最多1秒）
                task_data = self.redis_client.blpop(self.queue_name, timeout=1)

                if task_data:
                    _, task_json = task_data
                    task = json.loads(task_json)

                    # 移到处理中队列
                    await self._move_to_processing(task)

                    # 执行任务
                    asyncio.create_task(self._process_task(task))

            except Exception as e:
                logger.error(f"Error consuming task: {e}")
                await asyncio.sleep(1)

    async def _move_to_processing(self, task: dict):
        """移动任务到处理中队列"""
        task_id = task.get("task_id")
        if task_id and self.redis_client:
            self.redis_client.hset(
                self.processing_queue,
                task_id,
                json.dumps(task)
            )

    async def _process_task(self, task: dict):
        """处理任务"""
        task_id = task.get("task_id")

        try:
            result = await self.task_executor.execute_task(task)

            # 从处理中队列移除
            if self.redis_client:
                self.redis_client.hdel(self.processing_queue, task_id)

            # 发布结果到完成队列
            await self._publish_result(task_id, result)

        except Exception as e:
            logger.error(f"Failed to process task {task_id}: {e}")

    async def _publish_result(self, task_id: str, result: dict):
        """发布任务结果"""
        if self.redis_client:
            result_key = f"pentest:tasks:result:{task_id}"
            self.redis_client.setex(result_key, 3600, json.dumps(result))

            # 发布完成事件
            self.redis_client.publish("pentest:task_completed", task_id)

    def stop_consuming(self):
        """停止消费"""
        self.running = False
        logger.info("Stopped consuming from queue")