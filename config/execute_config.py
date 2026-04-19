"""Execution configuration - 支持多模型Provider"""

import os
from dotenv import load_dotenv

load_dotenv(".env")

SUPPORTED_PROVIDERS = {
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "env_key": "OPENROUTER_API_KEY",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "env_key": "OPENAI_API_KEY",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "env_key": "DEEPSEEK_API_KEY",
    },
    "siliconflow": {
        "base_url": "https://api.siliconflow.cn/v1",
        "env_key": "SILICONFLOW_API_KEY",
    },
    "custom": {
        "base_url": None,
        "env_key": "CUSTOM_API_KEY",
    },
}

PROVIDER = os.getenv("LLM_PROVIDER", "openrouter")

MODEL_NAME = os.getenv("MODEL_NAME", "z-ai/glm-5.1")

if PROVIDER == "custom":
    BASE_URL = os.getenv("CUSTOM_BASE_URL", "https://openrouter.ai/api/v1")
else:
    provider_config = SUPPORTED_PROVIDERS.get(
        PROVIDER, SUPPORTED_PROVIDERS["openrouter"]
    )
    BASE_URL = os.getenv("LLM_BASE_URL", provider_config["base_url"])

API_KEY = os.getenv("LLM_API_KEY") or os.getenv(
    SUPPORTED_PROVIDERS.get(PROVIDER, SUPPORTED_PROVIDERS["openrouter"])["env_key"],
    os.getenv("OPENROUTER_API_KEY", ""),
)

# 延迟验证API密钥，允许模块导入后再检查
def validate_api_key():
    """验证API密钥是否已设置"""
    if not API_KEY:
        raise ValueError(
            f"未设置API密钥。请设置 LLM_API_KEY 或 "
            f"{SUPPORTED_PROVIDERS.get(PROVIDER, {}).get('env_key', 'API_KEY')} 环境变量"
        )

OPENROUTER_API_KEY = API_KEY
OPENROUTER_BASE_URL = BASE_URL

LLM_CONFIG = {
    "model": MODEL_NAME,
    "base_url": BASE_URL,
    "api_key": API_KEY,
}
