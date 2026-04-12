"""
Task Queue Tests - 任务队列测试
"""

import pytest
from datetime import datetime

from src.core.queue import TaskQueue, TaskStatus, get_task_queue


@pytest.fixture
def queue():
    """创建测试队列实例（使用独立 Redis DB）"""
    TaskQueue.reset_instance()
    q = TaskQueue(redis_url="redis://localhost:6379/1")
    yield q
    try:
        q.client.flushdb()
    except:
        pass
    TaskQueue.reset_instance()


class TestEnqueueDequeue:
    """入队出队测试"""

    def test_enqueue_basic(self, queue):
        task_id = queue.enqueue({"task": "test", "data": 123})
        assert task_id.startswith("task_")
        assert queue.get_status(task_id) is not None

    def test_enqueue_with_priority(self, queue):
        # 高优先级（值大）先出队
        id_low = queue.enqueue({"task": "low"}, priority=10)
        id_high = queue.enqueue({"task": "high"}, priority=0)

        task = queue.dequeue(block=False)
        assert task["task_id"] == id_high

    def test_dequeue_blocking(self, queue):
        queue.enqueue({"task": "test"})
        task = queue.dequeue(block=True, timeout=5)
        assert task is not None
        assert task["status"] == TaskStatus.PROCESSING.value

    def test_dequeue_empty(self, queue):
        task = queue.dequeue(block=False)
        assert task is None


class TestTaskStatus:
    """任务状态测试"""

    def test_complete_task(self, queue):
        task_id = queue.enqueue({"task": "test"})
        queue.complete(task_id, {"result": "success"})

        status = queue.get_status(task_id)
        assert status["status"] == TaskStatus.COMPLETED.value
        assert status["result"]["result"] == "success"

    def test_fail_task_first_retry(self, queue):
        """测试任务第一次失败（会进入重试队列）"""
        task_id = queue.enqueue({"task": "test"})
        queue.fail(task_id, "Test error")

        status = queue.get_status(task_id)
        assert status["retries"] == 1
        assert status["status"] == TaskStatus.PENDING.value

    def test_fail_task_max_retries(self, queue):
        task_id = queue.enqueue({"task": "test"})

        for _ in range(3):
            queue.fail(task_id, "Test error")

        status = queue.get_status(task_id)
        assert status["status"] == TaskStatus.FAILED.value
        assert status["retries"] == 3


class TestRetryDelays:
    """重试延迟测试"""

    def test_retry_delay_calculation(self, queue):
        task_id = queue.enqueue({"task": "test"})
        queue.fail(task_id, "Error 1")

        status = queue.get_status(task_id)
        assert status["retries"] == 1

        retry_at = datetime.fromisoformat(status["retry_at"])
        delay = (retry_at - datetime.now()).total_seconds()
        assert pytest.approx(delay, abs=2) == 10

    def test_linear_retry_delays(self, queue):
        task_id = queue.enqueue({"task": "test"})
        queue.fail(task_id, "Error 1")
        queue.fail(task_id, "Error 2")

        status = queue.get_status(task_id)
        assert status["retries"] == 2

        retry_at = datetime.fromisoformat(status["retry_at"])
        delay = (retry_at - datetime.now()).total_seconds()
        assert pytest.approx(delay, abs=2) == 20


class TestQueueStats:
    """队列统计测试"""

    def test_get_stats_empty(self, queue):
        stats = queue.get_stats()
        assert stats["pending"] == 0
        assert stats["processing"] == 0
        assert stats["completed"] == 0
        assert stats["failed"] == 0

    def test_get_stats_with_tasks(self, queue):
        queue.enqueue({"task": "1"})
        queue.enqueue({"task": "2"})
        task = queue.dequeue(block=False)

        stats = queue.get_stats()
        assert stats["pending"] == 1
        assert stats["processing"] == 1


class TestTimeout:
    """超时测试"""

    def test_check_timeouts_none(self, queue):
        queue.enqueue({"task": "test"})
        count = queue.check_timeouts()
        assert count == 0


class TestSingleton:
    """单例测试"""

    def test_singleton(self):
        TaskQueue.reset_instance()
        q1 = get_task_queue()
        q2 = get_task_queue()
        assert q1 is q2

    def test_reset_instance(self):
        TaskQueue.reset_instance()
        q1 = get_task_queue()
        TaskQueue.reset_instance()
        q2 = get_task_queue()
        assert q1 is not q2
