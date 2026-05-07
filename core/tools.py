"""Tools for Kali Linux command execution."""

import re
from crewai.tools import BaseTool
from core.kali_executor import KaliExecutor
from typing import Type
from pydantic import BaseModel, Field

LONG_RUNNING_COMMANDS = {
    "nmap": 600,
    "hydra": 300,
    "masscan": 300,
    "gobuster": 180,
    "dirb": 180,
    "ffuf": 180,
    "nikto": 300,
    "sqlmap": 300,
    "wpscan": 300,
}


def _get_timeout_for_command(command: str) -> int:
    """根据命令类型返回合适的超时时间"""
    cmd_lower = command.lower()
    for pattern, timeout in LONG_RUNNING_COMMANDS.items():
        if pattern in cmd_lower:
            return timeout
    return 300


class KaliCommandInput(BaseModel):
    """Input schema for kali_command tool"""

    command: str = Field(
        ..., description="The shell command to execute in Kali Linux environment"
    )
    rationale: str = Field(
        "", description="Optional explanation for why this command is being executed"
    )


class KaliCommandTool(BaseTool):
    name: str = "kali_command"
    description: str = "Execute shell commands directly in Kali Linux environment. Use this tool to run security testing tools like nmap, sqlmap, etc."
    args_schema: Type[BaseModel] = KaliCommandInput

    def _run(self, command: str, rationale: str = "") -> str:
        """Execute command in Kali Linux environment."""
        timeout = _get_timeout_for_command(command)
        executor = KaliExecutor(timeout=timeout)
        return executor.execute(command)


class PythonExecuteInput(BaseModel):
    """Input schema for python_execute tool"""

    code: str = Field(..., description="Python code to execute")
    rationale: str = Field(
        "", description="Optional explanation for why this code is being executed"
    )


class PythonExecuteTool(BaseTool):
    name: str = "python_execute"
    description: str = "Execute Python code directly in Kali Linux environment"
    args_schema: Type[BaseModel] = PythonExecuteInput

    def _run(self, code: str, rationale: str = "") -> str:
        """Execute Python code in Kali Linux environment."""
        executor = KaliExecutor(timeout=120)
        return executor.execute_python(code)


# 创建工具实例
kali_command = KaliCommandTool()
python_execute = PythonExecuteTool()
