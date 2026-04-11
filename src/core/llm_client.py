"""
LLM Client - LLM 客户端封装
使用 litellm 支持多种 Provider（OpenRouter/OpenAI）
支持 streaming、async、function calling
"""

import os
import json
import threading
from typing import List, Dict, Any, Optional, Iterator, AsyncIterator
from loguru import logger

import litellm
from litellm import acompletion, completion
from langchain_openai import ChatOpenAI
from langchain_core.language_models import BaseChatModel

from .settings import get_settings


class LLMClient:
    """
    LLM 客户端封装

    支持：
    - 多 Provider 切换（openrouter/openai）
    - Streaming 输出
    - Async 调用
    - Function Calling
    - 自动降级（重试时切换模型）
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
        self._lock = threading.Lock()

        logger.info(
            f"LLMClient initialized: provider={self.provider}, model={self.model}"
        )

    def _get_default_model(self) -> str:
        """获取默认模型"""
        settings = get_settings()
        if self.provider == "openrouter":
            return settings.openrouter_model or "z-ai/glm-5.1"
        elif self.provider == "openai":
            return settings.openai_model or "gpt-4o"
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
        """切换到备用模型"""
        if not self._use_fallback:
            logger.warning(f"Switching to fallback model: {self._fallback_model}")
            self._use_fallback = True
            self.model = self._fallback_model

    def _get_api_key_for_call(self) -> str:
        """返回用于 API 调用的密钥"""
        return self.api_key

    def _get_base_url_for_call(self) -> Optional[str]:
        """返回用于 API 调用的 base_url"""
        settings = get_settings()
        if self.provider == "openrouter":
            return settings.openrouter_base_url or "https://openrouter.ai/api/v1"
        elif self.provider == "openai":
            return settings.openai_base_url or None
        return None

    def complete(
        self,
        messages: List[Dict[str, str]],
        stream: bool = False,
        tools: Optional[List[Dict]] = None,
        **kwargs,
    ) -> Any:
        """
        同步 completion

        Args:
            messages: 消息列表
            stream: 是否流式输出
            tools: 工具定义（用于 function calling）

        Returns:
            完整响应或流式迭代器
        """
        model = self._get_model_string()

        params = {
            "model": model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "api_key": self._get_api_key_for_call(),
            **kwargs,
        }

        base_url = self._get_base_url_for_call()
        if base_url:
            params["api_base"] = base_url

        if tools and self.is_function_calling_supported():
            params["tools"] = tools

        if stream:
            return completion(**params, stream=True)

        return completion(**params)

    async def acomplete(
        self,
        messages: List[Dict[str, str]],
        stream: bool = False,
        tools: Optional[List[Dict]] = None,
        **kwargs,
    ) -> Any:
        """
        异步 completion

        Args:
            messages: 消息列表
            stream: 是否流式输出
            tools: 工具定义（用于 function calling）

        Returns:
            完整响应或异步流式迭代器
        """
        model = self._get_model_string()

        params = {
            "model": model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "api_key": self._get_api_key_for_call(),
            **kwargs,
        }

        base_url = self._get_base_url_for_call()
        if base_url:
            params["api_base"] = base_url

        if tools and self.is_function_calling_supported():
            params["tools"] = tools

        if stream:
            return await acompletion(**params, stream=True)

        return await acompletion(**params)

    def get_langchain_llm(self) -> BaseChatModel:
        """
        获取 LangChain 兼容的 LLM

        Returns:
            ChatOpenAI 兼容对象
        """
        settings = get_settings()

        if self.provider == "openrouter":
            base_url = settings.openrouter_base_url or "https://openrouter.ai/api/v1"
            return ChatOpenAI(
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                base_url=base_url,
                api_key=self.api_key,
            )
        else:
            return ChatOpenAI(
                model=self.model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                api_key=self.api_key,
            )

    def get_tool_definitions(self) -> List[Dict]:
        """
        获取工具定义（用于 function calling）

        Returns:
            工具定义列表
        """
        return []


# 全局实例（线程安全单例）
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
