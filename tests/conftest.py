"""
测试配置
"""
import pytest
import asyncio
from typing import Generator


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """创建事件循环"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_target() -> str:
    """模拟目标"""
    return "127.0.0.1"


@pytest.fixture
def mock_context() -> dict:
    """模拟上下文"""
    return {
        "scan_id": "test-scan-001",
        "user_id": "test-user",
        "timeout": 300
    }