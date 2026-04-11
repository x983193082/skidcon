"""
Agent Interface - Agent抽象基类
所有具体Agent必须继承此类并实现抽象方法
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from enum import Enum


class AgentRole(Enum):
    """Agent角色枚举"""
    RECON = "recon"
    EXPLOIT = "exploit"
    PRIVILEGE = "privilege"
    REPORT = "report"


class AgentState(Enum):
    """Agent状态枚举"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class BaseAgent(ABC):
    """
    Agent抽象基类

    所有渗透测试Agent必须继承此类，实现以下核心方法：
    - execute: 执行Agent任务
    - validate_result: 验证执行结果
    - report: 生成报告
    """

    def __init__(
        self,
        name: str,
        role: AgentRole,
        description: str = "",
        tools: List[Any] = None,
        config: Dict[str, Any] = None
    ):
        self.name = name
        self.role = role
        self.description = description
        self.tools = tools or []
        self.config = config or {}
        self.state = AgentState.IDLE
        self._context: Dict[str, Any] = {}

    @abstractmethod
    async def execute(self, target: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        执行Agent任务

        Args:
            target: 目标地址/域名/IP
            context: 执行上下文（包含前置Agent的输出）

        Returns:
            执行结果字典
        """
        pass

    @abstractmethod
    def validate_result(self, result: Dict[str, Any]) -> bool:
        """
        验证执行结果的有效性

        Args:
            result: execute方法返回的结果

        Returns:
            结果是否有效
        """
        pass

    @abstractmethod
    def report(self) -> Dict[str, Any]:
        """
        生成Agent执行报告

        Returns:
            报告数据
        """
        pass

    def add_tool(self, tool: Any) -> None:
        """添加工具到Agent"""
        if tool not in self.tools:
            self.tools.append(tool)

    def remove_tool(self, tool: Any) -> None:
        """从Agent移除工具"""
        if tool in self.tools:
            self.tools.remove(tool)

    def set_context(self, context: Dict[str, Any]) -> None:
        """设置执行上下文"""
        self._context = context or {}

    def get_context(self) -> Dict[str, Any]:
        """获取当前上下文"""
        return self._context.copy()

    def update_state(self, new_state: AgentState) -> None:
        """更新Agent状态"""
        self.state = new_state

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name='{self.name}' role={self.role.value} state={self.state.value}>"