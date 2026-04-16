"""
SkidCon CrewAI Agent 定义
定义 4 个 Agent：PlannerAgent, ExecutorAgent, AnalyzerAgent, ReporterAgent
"""

from crewai import Agent
from langchain_openai import ChatOpenAI
from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, MODEL_NAME


def create_llm():
    """创建 LLM 实例"""
    return ChatOpenAI(
        openai_api_key=OPENROUTER_API_KEY,
        openai_api_base=OPENROUTER_BASE_URL,
        model_name=MODEL_NAME,
        temperature=0.7,
        max_tokens=4096
    )


def create_planner_agent() -> Agent:
    """创建规划 Agent"""
    return Agent(
        role="渗透测试规划专家",
        goal="分析目标系统，制定最优的渗透测试攻击路径和策略",
        backstory="""你是一位拥有 15 年经验的资深渗透测试专家，擅长分析目标系统并制定全面的攻击策略。
你熟悉各种渗透测试方法论（如 PTES、OWASP Testing Guide），能够根据目标特征选择最合适的工具和技术。
你的任务是分析目标 IP/URL，识别潜在的攻击面，并制定分阶段的测试计划。""",
        llm=create_llm(),
        verbose=True,
        allow_delegation=False
    )


def create_executor_agent() -> Agent:
    """创建执行 Agent"""
    return Agent(
        role="工具执行专家",
        goal="精确执行各类渗透测试工具，获取准确的扫描和测试结果",
        backstory="""你是一位精通各类渗透测试工具的安全工程师，熟练使用 Nmap、SQLMap、Metasploit、Burp Suite 等 50+ 安全工具。
你能够根据规划阶段的策略，精确配置和执行工具，获取准确的扫描结果。
你擅长解读工具输出，识别关键信息，并为后续分析阶段提供结构化数据。""",
        llm=create_llm(),
        verbose=True,
        allow_delegation=False
    )


def create_analyzer_agent() -> Agent:
    """创建分析 Agent"""
    return Agent(
        role="漏洞分析专家",
        goal="分析执行结果，识别真实漏洞，降低误报率，评估风险等级",
        backstory="""你是一位经验丰富的漏洞研究员，拥有 CVE 编号分配权限。
你擅长分析各种安全工具的输出结果，区分真实漏洞和误报。
你能够根据 CVSS 评分标准评估漏洞风险等级，并提供详细的漏洞描述和利用场景分析。
你的分析结果将直接用于生成最终的安全报告。""",
        llm=create_llm(),
        verbose=True,
        allow_delegation=False
    )


def create_reporter_agent() -> Agent:
    """创建报告 Agent"""
    return Agent(
        role="报告生成专家",
        goal="生成详细专业的渗透测试报告，提供可操作的修复建议",
        backstory="""你是一位专业的安全咨询顾问，擅长撰写高质量的渗透测试报告。
你的报告结构清晰、内容详实，包含执行摘要、漏洞详情、风险评级、修复建议等关键部分。
你能够用通俗易懂的语言解释技术漏洞，帮助客户理解安全风险并采取有效的修复措施。
你的报告符合行业标准（如 PTES、NIST SP 800-115）。""",
        llm=create_llm(),
        verbose=True,
        allow_delegation=False
    )


# Agent 工厂字典
AGENT_FACTORIES = {
    "planner": create_planner_agent,
    "executor": create_executor_agent,
    "analyzer": create_analyzer_agent,
    "reporter": create_reporter_agent,
}


def get_agent(agent_type: str) -> Agent:
    """获取指定类型的 Agent"""
    if agent_type in AGENT_FACTORIES:
        return AGENT_FACTORIES[agent_type]()
    raise ValueError(f"未知的 Agent 类型: {agent_type}")


def get_all_agents() -> dict:
    """获取所有 Agent"""
    return {
        "planner": create_planner_agent(),
        "executor": create_executor_agent(),
        "analyzer": create_analyzer_agent(),
        "reporter": create_reporter_agent()
    }
