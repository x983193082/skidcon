"""
Worker 主入口 - 连接 Redis 并启动任务处理
"""
import asyncio
import signal
import sys
from typing import Optional
import redis
from loguru import logger
from .task_executor import TaskExecutor
from .queue_handler import QueueHandler


class Worker:
    """Worker 服务主类"""

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.redis_url = redis_url
        self.redis_client: Optional[redis.Redis] = None
        self.task_executor: Optional[TaskExecutor] = None
        self.queue_handler: Optional[QueueHandler] = None
        self.running = False

    def connect(self) -> bool:
        """连接 Redis"""
        try:
            self.redis_client = redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            self.redis_client.ping()
            logger.info(f"Connected to Redis: {self.redis_url}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            return False

    def setup_components(self):
        """初始化组件"""
        self.task_executor = TaskExecutor(self.redis_client)
        self.queue_handler = QueueHandler(self.redis_client, self.task_executor)
        logger.info("Worker components initialized")

    async def start(self):
        """启动 Worker"""
        if not self.connect():
            sys.exit(1)

        self.setup_components()
        self.running = True

        logger.info("Worker started, waiting for tasks...")

        try:
            await self.queue_handler.start_consuming()
        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
        finally:
            await self.shutdown()

    async def shutdown(self):
        """关闭 Worker"""
        self.running = False
        if self.redis_client:
            self.redis_client.close()
        logger.info("Worker shutdown complete")


def main():
    """主入口函数"""
    import os
    from dotenv import load_dotenv

    load_dotenv()

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    logger.info("Starting Worker service...")

    worker = Worker(redis_url)
    asyncio.run(worker.start())


if __name__ == "__main__":
    main()