"""执行Agent - 负责循环执行和验证"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crewai import Agent
from prompts.executor_prompts import EXECUTOR_AGENT_PROMPT


class ExecutorAgent(Agent):
    """执行Agent - 负责执行渗透测试命令并循环验证结果"""
    
    def __init__(self, llm, **kwargs):
        
        super().__init__(
            name="Penetration Executor Agent",
            role="渗透测试执行专家",
            goal="执行渗透测试命令，验证攻击是否成功，循环检测直至完成测试",
            backstory=EXECUTOR_AGENT_PROMPT,
            verbose=True,
            allow_delegation=True,
            llm=llm,
            **kwargs
        )
    
    def execute_and_verify(self, commands: list, context: str) -> dict:
        """
        执行命令并验证结果
        
        Args:
            commands: 要执行的命令列表
            context: 当前渗透测试上下文
        
        Returns:
            执行结果字典
        """
        results = []
        
        for cmd in commands:
            results.append({
                "command": cmd,
                "status": "pending",
                "output": ""
            })
        
        return {
            "commands": results,
            "context": context,
            "iteration": 0
        }
    
    def should_continue(self, result: dict, max_iterations: int = 10) -> bool:
        """
        判断是否继续执行
        
        Args:
            result: 当前执行结果
            max_iterations: 最大迭代次数
        
        Returns:
            是否继续
        """
        if result.get("iteration", 0) >= max_iterations:
            return False
        
        if result.get("found_flag"):
            return False
        
        if result.get("status") == "completed":
            return False
        
        return True
