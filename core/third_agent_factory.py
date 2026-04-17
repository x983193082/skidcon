"""Level 3 Agent Factory: Tool Executors using CrewAI."""

from crewai import Agent
from config.execute_config import MODEL_NAME, LLM_CONFIG
from config.tools_manuals import TOOL_MANUALS
from core.tools import kali_command, python_execute
from langchain_openai import ChatOpenAI


def create_llm():
    """创建OpenRouter LLM实例"""
    return ChatOpenAI(
        model=LLM_CONFIG["model"],
        openai_api_base=LLM_CONFIG["base_url"],
        openai_api_key=LLM_CONFIG["api_key"],
        temperature=0.1,
    )


def build_tool_executor(tool_name: str):
    """Build a Level 3 agent executor for a specific tool using CrewAI."""
    if tool_name not in TOOL_MANUALS:
        raise ValueError(f"Unknown tool: {tool_name}")
    
    tool_manual = TOOL_MANUALS[tool_name]
    
    return Agent(
        role=f"{tool_name} 工具执行专家（三级Agent）",
        goal=f"使用 {tool_name} 工具完成安全测试任务",
        backstory=f"""你是 {tool_name} 工具的专用执行Agent。

⚠️【最高优先级 · 强制规则 · 不可违反】⚠️
- 你接收到任何具体可执行任务后，必须【立即】调用 kali_command 工具
- 你【禁止】仅输出分析、说明、计划、示例、伪代码或文字描述
- 你【禁止】使用"假设数据 / 示例数据 / 模拟结果 / 占位符内容"
- 你【禁止】在未真实执行的情况下，构造任何看似合理的返回结果
- 你【禁止】编造、猜测或补全不存在的输入数据
- 你【禁止】说"我将要执行 / 我会运行 / 假设存在某数据"等表述

⚠️【执行真实性约束（最高优先级）】⚠️
- 所有返回内容【必须】来源于 kali_command 的真实执行结果
- 若输入参数缺失、路径不存在、格式错误、工具不可用：
  - 仍然必须调用 kali_command
  - 原样返回真实的异常、报错或堆栈信息
- 在任何情况下，都不允许用"示例输出"代替真实执行结果

📘 工具说明书（必须严格遵守）：
{tool_manual['manual']}

📤 返回格式规范（必须严格匹配）：
{tool_manual['return_format']}

🧩 你的职责流程（不得省略）：
1. 接收上级二级Agent传来的【明确工具执行任务】
2. 严格按照工具说明书理解参数与输入要求
3. 编写【可被直接执行】的shell命令
4. 【立即】调用 kali_command 执行命令（禁止中途解释）
5. 从真实执行结果中提取 stdout / stderr
6. 严格按照返回格式规范输出【真实 JSON 结果】
7. 【执行完成后立即停止，不要再次调用工具或继续执行其他操作】
8. 一旦发现flag，立即终止所有任务，即刻返回flag

⚠️【执行次数限制（关键）】⚠️
- 你【只能】调用 kali_command 【一次】
- 执行完成后，直接返回结果，【禁止】再次调用工具
- 【禁止】在已有执行结果的基础上继续执行其他代码
- 【禁止】进行"进一步分析"、"继续处理"等额外操作
- 如果执行结果已经满足任务要求，立即返回，不要做多余的操作
""",
        llm=create_llm(),
        tools=[kali_command],
        verbose=True,
        allow_delegation=False,
    )


# 工具列表
TOOL_NAMES = list(TOOL_MANUALS.keys())

# 创建所有工具执行器
tool_executors = {
    tool_name: build_tool_executor(tool_name)
    for tool_name in TOOL_NAMES
}
