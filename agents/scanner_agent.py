"""端口扫描Agent - 负责信息收集"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crewai import Agent
from skills.nmap_scan.nmap_tool import NmapTool, QuickNmapTool, FullNmapTool
from prompts.scanner_prompts import SCANNER_AGENT_PROMPT


class ScannerAgent(Agent):
    """端口扫描Agent - 负责对目标进行端口扫描和服务识别"""
    
    def __init__(self, llm, **kwargs):
        tools = [
            NmapTool(),
            QuickNmapTool(),
            FullNmapTool()
        ]
        
        super().__init__(
            name="Port Scanner Agent",
            role="信息收集专家",
            goal="收集目标主机的端口、服务和版本信息",
            backstory=SCANNER_AGENT_PROMPT,
            verbose=True,
            allow_delegation=False,
            tools=tools,
            llm=llm,
            **kwargs
        )
    
    def scan_target(self, target: str, scan_type: str = "quick") -> str:
        """
        执行端口扫描
        
        Args:
            target: 目标主机
            scan_type: 扫描类型 (quick/full/custom)
        
        Returns:
            扫描结果
        """
        if scan_type == "quick":
            tool = QuickNmapTool()
            return tool._run(target=target)
        elif scan_type == "full":
            tool = FullNmapTool()
            return tool._run(target=target)
        else:
            tool = NmapTool()
            return tool._run(target=target)
