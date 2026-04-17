"""Tools for Kali Linux command execution."""

from crewai.tools import BaseTool
from core.kali_executor import KaliExecutor
from typing import Type
from pydantic import BaseModel, Field


class KaliCommandInput(BaseModel):
    """Input schema for kali_command tool"""
    command: str = Field(..., description="The shell command to execute in Kali Linux")
    rationale: str = Field("", description="Optional explanation for why this command is being executed")


class KaliCommandTool(BaseTool):
    name: str = "kali_command"
    description: str = "Execute shell commands directly in Kali Linux environment. Use this tool to run security testing tools like nmap, sqlmap, etc."
    args_schema: Type[BaseModel] = KaliCommandInput
    
    def _run(self, command: str, rationale: str = "") -> str:
        """Execute command in Kali Linux environment."""
        executor = KaliExecutor()
        return executor.execute(command)


class PythonExecuteInput(BaseModel):
    """Input schema for python_execute tool"""
    code: str = Field(..., description="Python code to execute")
    rationale: str = Field("", description="Optional explanation for why this code is being executed")


class PythonExecuteTool(BaseTool):
    name: str = "python_execute"
    description: str = "Execute Python code directly in Kali Linux environment"
    args_schema: Type[BaseModel] = PythonExecuteInput
    
    def _run(self, code: str, rationale: str = "") -> str:
        """Execute Python code in Kali Linux environment."""
        executor = KaliExecutor()
        return executor.execute_python(code)


# 创建工具实例
kali_command = KaliCommandTool()
python_execute = PythonExecuteTool()

