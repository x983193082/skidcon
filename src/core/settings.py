"""
Settings - Pydantic Settings 配置类
统一管理环境变量配置
"""

from typing import List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置类"""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    # API配置
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_workers: int = 4
    api_reload: bool = False

    # Redis配置
    redis_url: str = "redis://localhost:6379/0"
    redis_password: Optional[str] = None

    # 任务队列配置
    queue_task_ttl: int = 86400  # 24 小时
    queue_task_timeout: int = 300  # 5 分钟
    queue_max_retries: int = 3
    queue_retry_delays: List[int] = Field(default_factory=lambda: [10, 20, 30])
    queue_dead_letter_ttl: int = 604800  # 7 天

    # 向量数据库配置
    vector_db_type: str = "chroma"
    vector_db_url: str = "http://localhost:8000"
    vector_db_collection: str = "pentest_knowledge"

    # 图数据库配置
    neo4j_uri: Optional[str] = None
    neo4j_user: Optional[str] = None
    neo4j_password: Optional[str] = None

    # LLM配置
    llm_provider: str = "openrouter"
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o"
    openai_temperature: float = 0.7
    openai_base_url: Optional[str] = None

    # OpenRouter配置
    openrouter_api_key: Optional[str] = None
    openrouter_model: str = "z-ai/glm-5.1"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_site_url: Optional[str] = None
    openrouter_app_name: Optional[str] = None

    # LLM 重试配置
    llm_max_retries: int = 3
    llm_retry_delay: float = 1.0
    llm_max_retry_delay: float = 30.0
    llm_exponential_base: float = 2.0
    llm_timeout: int = 60

    # LLM 日志配置
    llm_log_retries: bool = True
    llm_log_level: str = "INFO"

    # LLM 响应解析配置
    llm_response_format: str = "json"
    llm_parse_errors_fallback: bool = True

    # Prompt 管理配置
    prompts_dir: str = "config/prompts"
    prompts_enable_runtime_update: bool = True
    prompts_version: str = "latest"

    # 安全工具配置
    nmap_path: str = "/usr/bin/nmap"
    sqlmap_path: str = "/usr/bin/sqlmap"
    metasploit_rpc_host: str = "localhost"
    metasploit_rpc_port: int = 55553

    # Docker沙箱配置
    docker_sandbox_enabled: bool = True
    docker_sandbox_image: str = "pentest-toolkit:latest"
    docker_sandbox_timeout: int = 300

    # 日志配置
    log_level: str = "INFO"
    log_format: str = "json"
    log_file: Optional[str] = None

    # 报告配置
    report_output_dir: str = "./reports"
    report_formats: List[str] = Field(default_factory=lambda: ["html", "pdf", "json"])

    # 安全配置
    max_concurrent_scans: int = 5
    scan_timeout: int = 3600
    allowed_targets: str = ""

    # 配置目录
    config_dir: str = "config"


# 全局配置实例
settings = Settings()


def get_settings() -> Settings:
    """获取全局配置实例"""
    return settings
