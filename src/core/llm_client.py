"""
LLM Client - LLM 客户端封装
使用 litellm 支持多种 Provider（OpenRouter/OpenAI）
支持 streaming、async、function calling、重试机制
"""

import os
import asyncio
import threading
from typing import List, Dict, Any, Optional
from loguru import logger

import litellm
from litellm import acompletion, completion
from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseChatModel

from .settings import get_settings


class LLMRetryError(Exception):
    """LLM 重试失败错误"""

    pass


class LLMClient:
    """
    LLM 客户端封装

    支持：
    - 多 Provider 切换（openrouter/openai）
    - Streaming 输出
    - Async 调用
    - Function Calling
    - 自动降级（重试时切换模型）
    - 重试机制（指数退避）
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs,
    ):
        settings = get_settings()

        self.provider = provider or settings.llm_provider
        self.model = model or self._get_default_model()
        self.temperature = temperature
        self.max_tokens = max_tokens

        self._setup_api_key()
        self._fallback_model = "gpt-4o"
        self._use_fallback = False
        self._lock = threading.RLock()  # 使用可重入锁

        # 安全获取配置，提供默认值避免 AttributeError
        self.max_retries = getattr(settings, "llm_max_retries", 3)
        self.retry_delay = getattr(settings, "llm_retry_delay", 1.0)
        self.max_retry_delay = getattr(settings, "llm_max_retry_delay", 60.0)
        self.exponential_base = getattr(settings, "llm_exponential_base", 2)
        self.timeout = getattr(settings, "llm_timeout", 60)
        self.log_retries = getattr(settings, "llm_log_retries", True)

        logger.info(
            f"LLMClient initialized: provider={self.provider}, model={self.model}, "
            f"max_retries={self.max_retries}, timeout={self.timeout}"
        )

    def _get_default_model(self) -> str:
        """获取默认模型"""
        settings = get_settings()
        if self.provider == "openrouter":
            return getattr(settings, "openrouter_model", "z-ai/glm-5.1")
        elif self.provider == "openai":
            return getattr(settings, "openai_model", "gpt-4o")
        return "gpt-4o"

    def _setup_api_key(self) -> None:
        """设置 API Key（不污染全局环境变量）"""
        settings = get_settings()

        if self.provider == "openrouter":
            self.api_key = settings.openrouter_api_key or os.getenv(
                "OPENROUTER_API_KEY"
            )
            if not self.api_key:
                raise ValueError("OPENROUTER_API_KEY not configured")

        elif self.provider == "openai":
            self.api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
            if not self.api_key:
                raise ValueError("OPENAI_API_KEY not configured")
        else:
            self.api_key = None

    def _get_model_string(self) -> str:
        """获取 litellm 模型字符串"""
        if self.provider == "openrouter":
            return f"openrouter/{self.model}"
        elif self.provider == "openai":
            return self.model
        return self.model

    def is_function_calling_supported(self) -> bool:
        """检查当前模型是否支持 function calling"""
        unsupported = ["o1", "o1-mini", "o1-preview"]
        return self.model not in unsupported

    def switch_to_fallback(self) -> None:
        """切换到备用模型（线程安全）"""
        with self._lock:
            if not self._use_fallback:
                logger.warning(f"Switching to fallback model: {self._fallback_model}")
                self._use_fallback = True
                self.model = self._fallback_model

    def reset_fallback(self) -> None:
        """重置回主模型（线程安全）"""
        with self._lock:
            if self._use_fallback:
                self._use_fallback = False
                self.model = self._get_default_model()
                logger.info(f"Fallback reset: restored to {self.model}")

    def _is_non_retryable_error(self, error: Exception) -> bool:
        """判断错误是否不应重试（基于类型和消息）"""
        # 先检查异常类型
        non_retryable_types = (
            litellm.exceptions.AuthenticationError,
            litellm.exceptions.BadRequestError,
            litellm.exceptions.PermissionError,
        )
        if isinstance(error, non_retryable_types):
            return True

        # 再检查错误消息
        error_str = str(error).lower()
        non_retryable_keywords = ["auth", "401", "403", "permission", "invalid api key"]
        return any(keyword in error_str for keyword in non_retryable_keywords)

    def _log_retry(self, level: str, message: str) -> None:
        """根据配置记录日志，安全地调用 logger 方法"""
        if self.log_retries:
            log_func = getattr(logger, level, logger.debug)
            log_func(message)

    def _get_api_key_for_call(self) -> Optional[str]:
        """返回用于 API 调用的密钥（可能为 None）"""
        return self.api_key

    def _get_base_url_for_call(self) -> Optional[str]:
        """返回用于 API 调用的 base_url"""
        settings = get_settings()
        if self.provider == "openrouter":
            return getattr(
                settings, "openrouter_base_url", "https://openrouter.ai/api/v1"
            )
        elif self.provider == "openai":
            return getattr(settings, "openai_base_url", None)
        return None

    def _build_params(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        stream: bool = False,
        **kwargs,
    ) -> Dict[str, Any]:
        """构建 API 调用参数"""
        model = self._get_model_string()

        params = {
            "model": model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            **kwargs,
        }

        api_key = self._get_api_key_for_call()
        if api_key:
            params["api_key"] = api_key

        base_url = self._get_base_url_for_call()
        if base_url:
            params["api_base"] = base_url

        if tools and self.is_function_calling_supported():
            params["tools"] = tools

        if self.timeout:
            params["timeout"] = self.timeout

        return params

    def complete(
        self,
        messages: List[Dict[str, str]],
        stream: bool = False,
        tools: Optional[List[Dict]] = None,
        **kwargs,
    ) -> Any:
        """同步 completion（带重试）"""
        return self._sync_retry_loop(
            self._do_complete, messages=messages, stream=stream, tools=tools, **kwargs
        )

    def _do_complete(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        stream: bool = False,
        **kwargs,
    ) -> Any:
        """执行实际的 completion 调用"""
        params = self._build_params(messages, tools, stream, **kwargs)
        if stream:
            return completion(**params, stream=True)
        return completion(**params)

    def _sync_retry_loop(self, func, *args, **kwargs) -> Any:
        """同步重试循环"""
        last_error = None

        for attempt in range(self.max_retries):
            try:
                if attempt > 0:
                    self._log_retry(
                        "info", f"Retry attempt {attempt + 1}/{self.max_retries}"
                    )
                return func(*args, **kwargs)

            except Exception as e:
                last_error = e
                self._log_retry(
                    "warning", f"LLM call failed (attempt {attempt + 1}): {e}"
                )

                if self._is_non_retryable_error(e):
                    self._log_retry("error", "Non-retryable error, stopping")
                    raise

                if attempt < self.max_retries - 1:
                    delay = min(
                        self.retry_delay * (self.exponential_base**attempt),
                        self.max_retry_delay,
                    )
                    self._log_retry("info", f"Retrying in {delay:.2f}s...")
                    import time

                    time.sleep(delay)

        self._log_retry("error", f"All {self.max_retries} retries exhausted")

        if not self._use_fallback:
            self._log_retry("info", "Attempting fallback model...")
            self.switch_to_fallback()
            try:
                return func(*args, **kwargs)
            except Exception as e:
                self._log_retry("error", f"Fallback also failed: {e}")
                raise LLMRetryError(
                    f"Primary and fallback both failed: {last_error}"
                ) from e

        raise LLMRetryError(f"All retries failed: {last_error}") from last_error

    async def acomplete(
        self,
        messages: List[Dict[str, str]],
        stream: bool = False,
        tools: Optional[List[Dict]] = None,
        **kwargs,
    ) -> Any:
        """异步 completion（带重试）"""
        return await self._async_retry_loop(
            self._do_acomplete, messages=messages, stream=stream, tools=tools, **kwargs
        )

    async def _do_acomplete(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        stream: bool = False,
        **kwargs,
    ) -> Any:
        """执行实际的异步 completion 调用"""
        params = self._build_params(messages, tools, stream, **kwargs)
        if stream:
            return await acompletion(**params, stream=True)
        return await acompletion(**params)

    async def _async_retry_loop(self, func, *args, **kwargs) -> Any:
        """异步重试循环"""
        last_error = None

        for attempt in range(self.max_retries):
            try:
                if attempt > 0:
                    self._log_retry(
                        "info", f"Retry attempt {attempt + 1}/{self.max_retries}"
                    )
                return await func(*args, **kwargs)

            except Exception as e:
                last_error = e
                self._log_retry(
                    "warning", f"LLM call failed (attempt {attempt + 1}): {e}"
                )

                if self._is_non_retryable_error(e):
                    self._log_retry("error", "Non-retryable error, stopping")
                    raise

                if attempt < self.max_retries - 1:
                    delay = min(
                        self.retry_delay * (self.exponential_base**attempt),
                        self.max_retry_delay,
                    )
                    self._log_retry("info", f"Retrying in {delay:.2f}s...")
                    await asyncio.sleep(delay)

        self._log_retry("error", f"All {self.max_retries} retries exhausted")

        if not self._use_fallback:
            self._log_retry("info", "Attempting fallback model...")
            self.switch_to_fallback()
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                self._log_retry("error", f"Fallback also failed: {e}")
                raise LLMRetryError(
                    f"Primary and fallback both failed: {last_error}"
                ) from e

        raise LLMRetryError(f"All retries failed: {last_error}") from last_error

    def get_langchain_llm(self) -> BaseChatModel:
        """获取 LangChain 兼容的 LLM"""
        settings = get_settings()

        # 构建参数字典，避免显式传递 None
        kwargs = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        if self.provider == "openrouter":
            base_url = getattr(
                settings, "openrouter_base_url", "https://openrouter.ai/api/v1"
            )
            kwargs["base_url"] = base_url

        # 仅当 api_key 非空时传递，让 LangChain 自动回退到环境变量
        if self.api_key:
            kwargs["api_key"] = self.api_key

        return ChatOpenAI(**kwargs)

    def get_tool_definitions(self) -> List[Dict]:
        """获取工具定义（用于 function calling）"""
        return []


_llm_client: Optional[LLMClient] = None
_llm_lock = threading.Lock()


def get_llm_client() -> LLMClient:
    """获取全局 LLM Client 实例（线程安全）"""
    global _llm_client
    if _llm_client is None:
        with _llm_lock:
            if _llm_client is None:
                _llm_client = LLMClient()
    return _llm_client


def reset_llm_client() -> None:
    """重置 LLM Client 实例（用于测试）"""
    global _llm_client
    with _llm_lock:
        _llm_client = None
