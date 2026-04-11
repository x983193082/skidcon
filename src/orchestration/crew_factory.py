"""
Crew Factory - 动态创建 CrewAI Crew
集成 LLM 客户端、知识库工具
迁移 prompt.yaml 内容到任务描述中
"""

import threading
from typing import Dict, Any, List, Optional, Type
from dataclasses import dataclass, field
from loguru import logger
from crewai import Agent, Task

from ..core.llm_client import LLMClient, get_llm_client
from ..core.crewai_adapter import CrewAIAdapter, get_crewai_adapter
from ..core.agent_interface import BaseAgent, AgentRole, AgentState
from ..agents.recon_agent import ReconAgent
from ..agents.exploit_agent import ExploitAgent
from ..agents.privilege_agent import PrivilegeAgent
from ..agents.report_agent import ReportAgent


@dataclass
class CrewConfig:
    """Crew 配置"""

    name: str
    agents: List[str] = field(default_factory=list)
    tasks: List[Dict[str, str]] = field(default_factory=list)
    process: str = "sequential"
    verbose: bool = True
    memory: bool = True
    max_rpm: int = 100


class CrewFactory:
    """
    Crew 工厂类

    负责创建和管理 CrewAI Crew 实例
    集成 LLM 客户端、知识库工具
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or get_llm_client()
        self.adapter = get_crewai_adapter()

        self._agent_registry: Dict[str, BaseAgent] = {}
        self._crews: Dict[str, Any] = {}
        self._lock = threading.RLock()

        logger.info("CrewFactory initialized")

    def register_base_agent(self, name: str, agent: BaseAgent) -> None:
        """注册 BaseAgent"""
        with self._lock:
            self._agent_registry[name] = agent
            logger.info(f"Registered agent: {name}")

    def create_crew(self, config: CrewConfig) -> Any:
        """根据配置创建 Crew"""
        agents = []
        tasks = []

        for agent_name in config.agents:
            if agent_name in self._agent_registry:
                base_agent = self._agent_registry[agent_name]
                crewai_agent = self.adapter.create_agent(base_agent)
                agents.append(crewai_agent)
            else:
                logger.warning(f"Agent '{agent_name}' not registered, skipping")

        for i, task_config in enumerate(config.tasks):
            if i < len(agents):
                task = self.adapter.create_task(
                    description=task_config.get("description", ""),
                    expected_output=task_config.get("expected_output", ""),
                    agent=agents[i],
                    verbose=config.verbose,
                )
                tasks.append(task)
            else:
                logger.error(f"Task {i} has no corresponding agent")

        crew = self.adapter.create_crew(
            agents=agents,
            tasks=tasks,
            process=config.process,
            verbose=config.verbose,
            memory=config.memory,
            max_rpm=config.max_rpm,
        )

        with self._lock:
            self._crews[config.name] = crew
        return crew

    def create_pentest_crew(
        self,
        target: str,
        scope: Optional[List[str]] = None,
        include_recon: bool = True,
        include_exploit: bool = True,
        include_privilege: bool = True,
        include_report: bool = True,
    ) -> Any:
        """创建完整渗透测试 Crew"""
        logger.info(f"Creating pentest crew for target: {target}")

        agents = []
        tasks = []

        # ========== Recon Agent ==========
        if include_recon:
            recon_agent = self._create_recon_agent(target)
            agents.append(recon_agent)

            recon_task = self.adapter.create_task(
                description=f"""对目标 {target} 进行信息收集和侦察。

## 1. 端口扫描
发现目标的所有开放端口，使用 nmap 进行快速扫描和详细扫描。

## 2. 服务指纹识别
根据发现的端口服务，识别详细的服务版本和配置。
- 分析服务 Banner 信息
- 推断详细的服务版本
- 识别操作系统信息
- 列出潜在漏洞

## 3. Web 技术栈分析
如果目标有 Web 服务，分析：
- 识别 Web 应用架构和技术栈
- 识别潜在的安全问题

## 4. 子域名枚举
枚举目标域名的子域名，发现隐藏的资源。

## 5. CVE 查询
对识别出的服务，使用搜索工具查询相关 CVE：
- 查询已知漏洞
- 评估利用可行性
- 提供修复建议

## 6. 漏洞初步识别
综合分析所有收集到的信息，识别潜在的攻击面和安全风险。
""",
                expected_output="""完整的侦察报告，包含：
- 所有开放端口列表（按危险程度排序）
- 服务版本信息（详细到具体版本号）
- Web 技术栈分析结果
- 子域名列表
- 相关 CVE 列表（包含 CVSS 评分）
- 潜在漏洞类型列表
- 攻击建议（按优先级排序）
- 识别出的攻击面总结
""",
                agent=recon_agent,
            )
            tasks.append(recon_task)

        # ========== Exploit Agent ==========
        if include_exploit:
            exploit_agent = self._create_exploit_agent(target)
            agents.append(exploit_agent)

            exploit_task = self.adapter.create_task(
                description=f"""利用发现的漏洞对目标 {target} 进行渗透。

## 1. 分析侦察结果
- 综合分析侦察阶段收集的所有信息
- 评估每个漏洞的利用可行性和影响范围
- 确定最佳利用路径

## 2. CVE 分析
- 分析每个 CVE 的利用条件
- 评估利用可行性
- 确定影响范围
- 提供修复建议

## 3. 选择利用方式
根据漏洞列表，选择最佳利用方式：
- 推荐利用方式
- 所需工具（SQLMap、POC 脚本等）
- 详细利用步骤

## 4. Shell 获取
选择最合适的反弹 Shell 方式：
- 根据目标 OS 类型选择
- 根据已有访问权限选择
- 推荐最佳 Shell 获取方式

## 5. 载荷生成
生成针对场景的攻击载荷：
- 根据目标类型生成
- 根据操作系统选择
- 返回可用载荷

## 6. 执行漏洞利用
- 使用 SQLMap 测试 SQL 注入
- 使用 POC 脚本验证漏洞
- 获取目标访问权限
- 获取初始 shell
""",
                expected_output="""渗透测试报告，包含：
- 成功利用的漏洞列表
- CVE 分析详情（利用条件、可行性、影响范围）
- 推荐的利用方式和工具
- Shell 获取信息（类型、目标地址、端口）
- 详细的利用过程记录
- 失败尝试及原因
- 获取的访问权限详情
""",
                agent=exploit_agent,
            )
            tasks.append(exploit_task)

        # ========== Privilege Agent ==========
        if include_privilege:
            privilege_agent = self._create_privilege_agent(target)
            agents.append(privilege_agent)

            privilege_task = self.adapter.create_task(
                description=f"""对已获取权限的系统进行权限提升。

## 1. 分析当前权限
- 检查当前用户和组信息
- 枚举 SUID 文件
- 检查 sudo 权限
- 识别可用的提权向量

## 2. OS 信息收集
- 检测操作系统类型和版本
- 收集内核版本信息
- 收集系统配置信息

## 3. 提权向量枚举
- 枚举所有可能的提权方法
- Linux: sudo, suid, capabilities, cron, docker, kernel
- Windows: always_install_elevated, service_path, service_permission, token, scheduled_task

## 4. 选择最佳提权方法
根据枚举结果选择最有效的提权方法：
- 推荐方法
- 利用命令
- 风险评估

## 5. 执行提权
- 尝试各种提权方法
- 记录成功的提权路径
- 获取更高权限

## 6. 建立持久化
在目标系统建立长期访问：
- Linux: cron, ssh_key, rc_local, bashrc
- Windows: registry_run, scheduled_task, service, wmi_event
- 返回最佳持久化方案
""",
                expected_output="""权限提升报告，包含：
- 当前权限信息（用户、组）
- OS 类型和版本
- 可利用的提权向量列表（按优先级）
- 成功提升的权限
- 提权过程记录
- 持久化配置详情
- 风险评估
""",
                agent=privilege_agent,
            )
            tasks.append(privilege_task)

        # ========== Report Agent ==========
        if include_report:
            report_agent = self._create_report_agent(target)
            agents.append(report_agent)

            report_task = self.adapter.create_task(
                description=f"""汇总所有渗透测试结果，生成专业报告。

## 1. 汇总所有发现
- 收集侦察阶段发现
- 收集漏洞利用结果
- 收集权限提升结果

## 2. 风险评估
评估所有漏洞的风险等级：
- 使用 CVSS 评分
- 生成风险矩阵
- 确定修复优先级

## 3. 生成执行摘要
- 总发现数统计
- 按严重程度分类（严重/高危/中危/低危）
- Shell 获取情况
- 提权成功与否
- 简洁的总结（不超过 100 字）

## 4. 生成漏洞详情
为每个漏洞生成详细报告：
- CVE ID 和描述
- 影响分析
- 利用证据
- 技术细节

## 5. 提供修复建议
按优先级排序的修复建议：
- 针对每个漏洞的修复方案
- 整体安全改进建议
- 短期和长期建议
""",
                expected_output="""完整的安全测试报告，包含：
- 执行摘要（简洁版）
- 风险评分（综合评分 0-10）
- 漏洞详情列表（按严重程度排序）
- 每个漏洞的详细技术报告
- 按优先级排序的修复建议
- 整体安全评估
- 后续行动建议
- 附录（工具输出、截图等）
""",
                agent=report_agent,
            )
            tasks.append(report_task)

        crew = self.adapter.create_crew(
            agents=agents, tasks=tasks, process="sequential", verbose=True, memory=True
        )

        with self._lock:
            self._crews["pentest"] = crew
        logger.info(f"Created pentest crew with {len(agents)} agents")

        return crew

    def _create_recon_agent(self, target: str) -> Agent:
        """创建侦察 Agent"""
        base_agent = ReconAgent(name="ReconAgent", description="负责目标信息收集和侦察")
        return self.adapter.create_agent(base_agent=base_agent)

    def _create_exploit_agent(self, target: str) -> Agent:
        """创建漏洞利用 Agent"""
        base_agent = ExploitAgent(
            name="ExploitAgent", description="负责漏洞验证和利用，获取初始访问"
        )
        return self.adapter.create_agent(base_agent=base_agent)

    def _create_privilege_agent(self, target: str) -> Agent:
        """创建权限提升 Agent"""
        base_agent = PrivilegeAgent(
            name="PrivilegeAgent", description="负责权限提升和持久化"
        )
        return self.adapter.create_agent(base_agent=base_agent)

    def _create_report_agent(self, target: str) -> Agent:
        """创建报告生成 Agent"""
        base_agent = ReportAgent(name="ReportAgent", description="负责生成渗透测试报告")
        return self.adapter.create_agent(base_agent=base_agent)

    def create_recon_crew(self, target: str) -> Any:
        """创建信息收集 Crew"""
        return self.create_pentest_crew(
            target=target,
            include_exploit=False,
            include_privilege=False,
            include_report=False,
        )

    def create_exploit_crew(self, target: str, vulnerabilities: List[Dict]) -> Any:
        """创建漏洞利用 Crew"""
        crew = self.create_pentest_crew(
            target=target,
            include_recon=False,
            include_privilege=False,
            include_report=False,
        )
        with self._lock:
            self._crews["exploit"] = crew
        return crew

    def create_report_crew(self, findings: List[Dict]) -> Any:
        """创建报告生成 Crew"""
        crew = self.create_pentest_crew(
            target="",
            include_recon=False,
            include_exploit=False,
            include_privilege=False,
            include_report=True,
        )
        with self._lock:
            self._crews["report"] = crew
        return crew

    def get_crew(self, name: str) -> Optional[Any]:
        """获取已创建的 Crew"""
        with self._lock:
            return self._crews.get(name)

    def list_crews(self) -> List[str]:
        """列出所有 Crew"""
        with self._lock:
            return list(self._crews.keys())


# 全局实例（线程安全）
_crew_factory: Optional[CrewFactory] = None
_factory_lock = threading.Lock()


def get_crew_factory() -> CrewFactory:
    """获取全局 CrewFactory 实例"""
    global _crew_factory
    if _crew_factory is None:
        with _factory_lock:
            if _crew_factory is None:
                _crew_factory = CrewFactory()
    return _crew_factory
