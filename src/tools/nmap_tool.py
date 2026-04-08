from crewai_tools import BaseTool
import subprocess
import json
from typing import Type
from pydantic import BaseModel, Field

class NmapInput(BaseModel):
    target: str = Field(..., description="要扫描的目标IP地址或域名")
    options: str = Field("-sV -O", description="Nmap扫描选项，默认为服务版本检测和操作系统识别")

class NmapScanTool(BaseTool):
    name:str = "Nmap扫描工具"
    description:str = "使用Nmap进行网络扫描，识别开放端口、服务版本和操作系统信息"
    args_schema: Type[BaseModel] = NmapInput

    def _run(self,target: str) -> str:
        try:
            # -F 快速扫描，-sV 服务版本检测，-O 操作系统识别（可选）
            result = subprocess.run(
                ["nmap","-F","-sV", target],
                capture_output=True,
                text=True,
                timeout=60,
            )
            return result.stdout if result.stdout else f"扫描完成，未发现开放端口：\n{result.stderr}"
        except subprocess.TimeoutExpired:
            return "扫描超时(60秒)，目标可能不可达或响应过慢"
        except Exception as e:
            return f"扫描过程中发生错误: {str(e)}"