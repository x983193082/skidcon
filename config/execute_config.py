"""Execution configuration for CrewAI agents."""

import os
from dotenv import load_dotenv

load_dotenv(".env")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "z-ai/glm-5.1")

# 验证必要的环境变量
if not OPENROUTER_API_KEY:
    raise ValueError("未设置 OPENROUTER_API_KEY 环境变量")

# CrewAI 模型配置格式
# CrewAI 使用 'provider/model' 格式
LLM_CONFIG = {
    "model": MODEL_NAME,
    "base_url": OPENROUTER_BASE_URL,
    "api_key": OPENROUTER_API_KEY,
}

