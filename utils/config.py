"""PentestAI配置模块"""

import os
import json
from typing import Optional
from pydantic import BaseModel
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

api_key = os.getenv("OPENROUTER_API_KEY", "")
os.environ["OPENROUTER_API_KEY"] = api_key

import litellm
litellm.drop_params = True


class PentestAIConfig(BaseModel):
    """PentestAI配置"""
    
    openrouter_api_key: str = api_key
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    default_model: str = "z-ai/glm-5"
    
    max_iterations: int = 10
    verbose: bool = True
    
    nmap_path: str = "nmap"
    
    workspace: str = "./workspace"
    logs_dir: str = "./logs"
    results_dir: str = "./results"
    
    class Config:
        arbitrary_types_allowed = True


def get_workspace_path() -> str:
    """获取工作目录路径"""
    config = get_config()
    return config.workspace


def get_logs_dir() -> str:
    """获取日志目录路径"""
    config = get_config()
    os.makedirs(config.logs_dir, exist_ok=True)
    return config.logs_dir


def get_results_dir() -> str:
    """获取结果目录路径"""
    config = get_config()
    os.makedirs(config.results_dir, exist_ok=True)
    return config.results_dir


def generate_session_id() -> str:
    """生成会话ID"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def get_log_file_path(session_id: str = None) -> str:
    """获取日志文件路径"""
    logs_dir = get_logs_dir()
    if session_id:
        return os.path.join(logs_dir, f"pentest_{session_id}.log")
    return os.path.join(logs_dir, f"pentest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")


def get_result_file_path(session_id: str = None) -> str:
    """获取结果文件路径"""
    results_dir = get_results_dir()
    if session_id:
        return os.path.join(results_dir, f"result_{session_id}.json")
    return os.path.join(results_dir, f"result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")


def save_result(session_id: str, data: dict) -> str:
    """保存渗透测试结果"""
    result_path = get_result_file_path(session_id)
    with open(result_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return result_path


def save_log(session_id: str, message: str, level: str = "INFO") -> None:
    """保存日志"""
    log_path = get_log_file_path(session_id)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_message = f"[{timestamp}] [{level}] {message}\n"
    
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(log_message)


def get_config() -> PentestAIConfig:
    """获取配置"""
    return PentestAIConfig()


def get_llm(model: str = None):
    """获取兼容的LLM实例"""
    config = get_config()
    model = model or config.default_model
    
    from crewai.llm import LLM
    
    return LLM(
        model=model,
        api_key=config.openrouter_api_key,
        base_url=config.openrouter_base_url,
        custom_llm_provider="openrouter"
    )
