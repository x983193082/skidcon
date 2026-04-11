"""
CrewAI Adapter - CrewAI 适配器
将现有 Agent 和工具封装为 CrewAI 组件
支持 streaming 输出和任务状态持久化
"""

import threading
from typing import List, Dict, Any, Optional, Callable, Union
from loguru import logger
from crewai import Agent, Task, Crew, Process

from .llm_client import LLMClient, get_llm_client
from .knowledge_tools import AVAILABLE_KNOWLEDGE_TOOLS, get_knowledge_tools
from .agent_interface import BaseAgent, AgentRole


class CrewAIAdapter:
    """
    CrewAI 适配器

    职责：
    - 将现有 BaseAgent 转换为 CrewAI Agent
    - 封装工具为 CrewAI 工具
    - 创建和管理 Crew
    - 支持 streaming 输出
    - 支持任务状态持久化
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or get_llm_client()
        self.llm = self.llm_client.get_langchain_llm()
        self.knowledge_tools = get_knowledge_tools()

    def create_agent(
        self, base_agent: BaseAgent, extra_tools: Optional[List[Any]] = None, **kwargs
    ) -> Agent:
        """
        将现有 BaseAgent 转换为 CrewAI Agent

        Args:
            base_agent: 现有 BaseAgent 实例
            extra_tools: 额外的工具（知识库工具等）

        Returns:
            CrewAI Agent
        """
        role = self._get_agent_role(base_agent.role)
        goal = self._get_agent_goal(base_agent.role)
        backstory = self._get_agent_backstory(base_agent.role, base_agent.description)

        tools = list(getattr(base_agent, "tools", [])) or []

        if extra_tools:
            tools.extend(extra_tools)

        tools.extend(AVAILABLE_KNOWLEDGE_TOOLS)

        crewai_agent = Agent(
            role=role,
            goal=goal,
            backstory=backstory,
            llm=self.llm,
            tools=tools,
            verbose=kwargs.get("verbose", True),
            max_iter=kwargs.get("max_iterations", 20),
            allow_delegation=kwargs.get("allow_delegation", False),
            memory=kwargs.get("memory", True),
        )

        logger.info(f"Created CrewAI Agent: {role} with {len(tools)} tools")
        return crewai_agent

    def create_task(
        self, description: str, expected_output: str, agent: Agent, **kwargs
    ) -> Task:
        """
        创建 CrewAI Task

        Args:
            description: 任务描述
            expected_output: 期望输出
            agent: 关联的 Agent

        Returns:
            CrewAI Task
        """
        return Task(
            description=description,
            expected_output=expected_output,
            agent=agent,
            verbose=kwargs.get("verbose", True),
            async_execution=kwargs.get("async_execution", False),
        )

    def create_crew(
        self,
        agents: List[Agent],
        tasks: List[Task],
        process: str = "sequential",
        verbose: bool = True,
        **kwargs,
    ) -> Crew:
        """
        创建 CrewAI Crew

        Args:
            agents: Agent 列表
            tasks: Task 列表
            process: 执行流程（sequential/hierarchical）
            verbose: 是否详细输出

        Returns:
            CrewAI Crew
        """
        crew = Crew(
            agents=agents,
            tasks=tasks,
            process=Process.SEQUENTIAL
            if process == "sequential"
            else Process.HIERARCHICAL,
            verbose=verbose,
            memory=kwargs.get("memory", True),
            max_rpm=kwargs.get("max_rpm", 100),
            share_crew=kwargs.get("share_crew", False),
        )

        logger.info(f"Created Crew with {len(agents)} agents, {len(tasks)} tasks")
        return crew

    async def run_crew(
        self,
        crew: Crew,
        inputs: Dict[str, Any],
        stream_handler: Optional[Callable] = None,
        task_store: Optional[Any] = None,
        task_id: Optional[str] = None,
    ) -> Any:
        """
        执行 Crew（支持流式回调）

        Args:
            crew: CrewAI Crew 实例
            inputs: 输入参数
            stream_handler: 流式输出回调 async def(event_type: str, data: Dict)
            task_store: 任务状态存储（需实现 update_status 方法）
            task_id: 任务 ID（用于持久化）

        Returns:
            Crew 执行结果
        """
        logger.info(f"Starting crew execution with inputs: {inputs}")

        if task_store and task_id:
            await task_store.update_status(task_id, "running", "starting")

        if stream_handler:
            await stream_handler("crew_started", {"inputs": inputs})

        try:
            import asyncio

            result = await asyncio.to_thread(crew.kickoff, inputs=inputs)

            if stream_handler:
                await stream_handler("crew_completed", {"result": str(result)})

            if task_store and task_id:
                await task_store.update_status(task_id, "completed", "finished")

            return result

        except Exception as e:
            logger.error(f"Crew execution failed: {e}")

            if stream_handler:
                await stream_handler("crew_failed", {"error": str(e)})

            if task_store and task_id:
                await task_store.update_status(task_id, "failed", str(e))

            raise

    def _get_agent_role(self, role: AgentRole) -> str:
        """获取 Agent 角色名称"""
        role_map = {
            AgentRole.RECON: "Reconnaissance Specialist",
            AgentRole.EXPLOIT: "Exploitation Expert",
            AgentRole.PRIVILEGE: "Privilege Escalation Specialist",
            AgentRole.REPORT: "Security Report Analyst",
        }
        return role_map.get(role, "Security Expert")

    def _get_agent_goal(self, role: AgentRole) -> str:
        """获取 Agent 目标"""
        goal_map = {
            AgentRole.RECON: "发现目标的所有开放端口、服务版本、Web 技术栈和潜在入口点",
            AgentRole.EXPLOIT: "利用发现的漏洞获取目标访问权限，获取初始 shell",
            AgentRole.PRIVILEGE: "在已获取权限的基础上进行权限提升和持久化",
            AgentRole.REPORT: "收集并分析渗透测试结果，生成专业的安全报告",
        }
        return goal_map.get(role, "完成安全评估任务")

    def _get_agent_backstory(self, role: AgentRole, description: str) -> str:
        """获取 Agent 背景故事"""
        backstory_map = {
            AgentRole.RECON: """你是一名专业的渗透测试工程师，精通各种信息收集和扫描技术。
            你熟悉 Nmap、Masscan 等扫描工具，能够快速识别目标的网络拓扑和开放服务。
            你还擅长 Web 技术识别、子域名枚举等服务发现技术。""",
            AgentRole.EXPLOIT: """你是一名漏洞利用专家，精通各种 Web 漏洞和系统漏洞的利用。
            你熟悉 SQLMap、各类 POC 脚本的使用，能够快速验证和利用发现的漏洞。
            你擅长获取目标 shell 并进行初步的权限维持。""",
            AgentRole.PRIVILEGE: """你是一名权限提升专家，熟悉各种系统和应用的提权技术。
            你了解 Linux 和 Windows 的各种提权方法，能够在获取初始 shell 后快速提升权限。""",
            AgentRole.REPORT: """你是一名资深安全分析师，擅长将复杂的渗透测试结果整理成专业的报告。
            你能够准确评估漏洞风险等级，并提供有效的安全建议。""",
        }

        base = backstory_map.get(role, "")
        if description:
            base += f" {description}"
        return base


# 全局实例（线程安全）
_crewai_adapter: Optional[CrewAIAdapter] = None
_adapter_lock = threading.Lock()


def get_crewai_adapter() -> CrewAIAdapter:
    """获取全局 CrewAI Adapter 实例"""
    global _crewai_adapter
    if _crewai_adapter is None:
        with _adapter_lock:
            if _crewai_adapter is None:
                _crewai_adapter = CrewAIAdapter()
    return _crewai_adapter
