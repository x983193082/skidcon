"""扩展工具基类 - 用于添加更多渗透测试工具"""

from crewai.tools import BaseTool
from pydantic import BaseModel
from typing import Type, Optional
import subprocess
import json


class ToolInput(BaseModel):
    """通用工具输入基类"""
    target: str
    extra_args: Optional[str] = ""


class SubprocessTool(BaseTool):
    """通用的Subprocess执行工具 - 用于执行任意命令行工具"""
    
    name: str = "execute_command"
    description: str = "执行命令行工具，用于运行各种渗透测试工具"
    args_schema: Type[BaseModel] = ToolInput

    def __init__(self, command_template: str, **kwargs):
        super().__init__(**kwargs)
        self.command_template = command_template

    def _run(self, target: str, extra_args: str = "") -> str:
        """执行命令模板"""
        cmd = self.command_template.format(target=target, extra=extra_args)
        
        try:
            result = subprocess.run(
                cmd.split(),
                capture_output=True,
                text=True,
                timeout=300
            )
            
            return result.stdout if result.stdout else result.stderr
            
        except Exception as e:
            return f"执行错误: {str(e)}"


class ReconTool(BaseTool):
    """信息收集工具 - 收集目标基础信息"""
    
    name: str = "reconnaissance"
    description: str = "收集目标的基础信息，如DNS解析、Whois查询等"
    args_schema: Type[BaseModel] = ToolInput

    def _run(self, target: str, extra_args: str = "") -> str:
        """执行信息收集"""
        results = []
        
        try:
            result = subprocess.run(
                ["nslookup", target],
                capture_output=True,
                text=True,
                timeout=30
            )
            results.append(f"DNS解析:\n{result.stdout}")
        except:
            pass
        
        try:
            result = subprocess.run(
                ["ping", "-c", "4", target],
                capture_output=True,
                text=True,
                timeout=30
            )
            results.append(f"Ping测试:\n{result.stdout}")
        except:
            pass
        
        return "\n\n".join(results) if results else "无法获取信息"


class WebDiscoveryTool(BaseTool):
    """Web目录发现工具"""
    
    name: str = "web_directory_discovery"
    description: str = "发现Web目录和文件，用于Web渗透测试的信息收集阶段"
    args_schema: Type[BaseModel] = ToolInput

    def _run(self, target: str, extra_args: str = "") -> str:
        """执行目录扫描"""
        wordlist = "/usr/share/wordlists/dirb/common.txt" if extra_args == "" else extra_args
        
        try:
            result = subprocess.run(
                ["gobuster", "dir", "-u", f"http://{target}", "-w", wordlist, "-q"],
                capture_output=True,
                text=True,
                timeout=300
            )
            return result.stdout if result.stdout else result.stderr
        except FileNotFoundError:
            return "gobuster未安装"
        except Exception as e:
            return f"错误: {str(e)}"
