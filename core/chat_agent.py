"""Chat agent for non-tool conversations using CrewAI."""

from crewai import Agent
from config.execute_config import MODEL_NAME, LLM_CONFIG
from langchain_openai import ChatOpenAI


def create_llm():
    """创建OpenRouter LLM实例"""
    return ChatOpenAI(
        model=LLM_CONFIG["model"],
        openai_api_base=LLM_CONFIG["base_url"],
        openai_api_key=LLM_CONFIG["api_key"],
        temperature=0.7,
    )


chat_agent = Agent(
    role="闲聊助手",
    goal="回答用户不需要工具的问题",
    backstory="""你是闲聊助手。
当用户的问题不需要调用任何漏洞/扫描/执行类工具时，请直接用自然语言回答。
如果用户要求进行现实世界的攻击、入侵或其他违法/高风险操作，请礼貌拒绝，并改为提供安全的、合规的科普或防护建议。
""",
    llm=create_llm(),
    verbose=True,
    allow_delegation=False,
)
