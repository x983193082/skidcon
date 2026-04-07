"""决策Agent - 负责制定渗透测试策略"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crewai import Agent
from prompts.planner_prompts import PLANNER_AGENT_PROMPT


class PlannerAgent(Agent):
    """决策制定Agent - 负责根据扫描结果制定渗透测试策略"""
    
    def __init__(self, llm, **kwargs):
        
        super().__init__(
            name="Strategy Planner Agent",
            role="渗透策略专家",
            goal="分析扫描结果，制定最佳的渗透测试策略和攻击路径",
            backstory=PLANNER_AGENT_PROMPT,
            verbose=True,
            allow_delegation=True,
            llm=llm,
            **kwargs
        )
    
    def analyze_and_plan(self, scan_results: str) -> dict:
        """
        分析扫描结果并制定策略
        
        Args:
            scan_results: 端口扫描结果
        
        Returns:
            包含策略建议的字典
        """
        prompt = f"""
基于以下扫描结果，请制定渗透测试策略:

{scan_results}

请提供:
1. 识别的服务和版本
2. 可能的漏洞点
3. 推荐的渗透测试路径
4. 优先测试的目标
"""
        
        return {"analysis_prompt": prompt}
