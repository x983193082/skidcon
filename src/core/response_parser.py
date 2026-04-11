"""
Response Parser - LLM 响应解析
"""

import json
import re
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum

from loguru import logger


class ResponseFormat(Enum):
    JSON = "json"
    MARKDOWN = "markdown"
    PLAIN = "plain"


@dataclass
class LLMResponse:
    content: str
    format: ResponseFormat
    raw_response: Any
    tool_calls: Optional[List[Dict]] = None
    usage: Optional[Dict] = None


class ResponseParser:
    """LLM 响应解析器"""

    @staticmethod
    def parse(
        response: Any, expected_format: ResponseFormat = ResponseFormat.JSON
    ) -> LLMResponse:
        """解析 LLM 响应"""
        content = ResponseParser._extract_content(response)
        tool_calls = ResponseParser._extract_tool_calls(response)
        usage = ResponseParser._extract_usage(response)

        return LLMResponse(
            content=content,
            format=expected_format,
            raw_response=response,
            tool_calls=tool_calls,
            usage=usage,
        )

    @staticmethod
    def parse_json(content: str) -> Optional[Dict]:
        """
        解析 JSON 内容
        支持：
        1. 直接 JSON 字符串
        2. Markdown 代码块中的 JSON
        3. 带前后文本的 JSON
        """
        if not content:
            return None

        content = content.strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        json_patterns = [
            r"```json\s*(.*?)\s*```",
            r"```\s*(.*?)\s*```",
            r"\{[^{}]*\}",
        ]

        for pattern in json_patterns:
            match = re.search(pattern, content, re.DOTALL)
            if match:
                try:
                    return json.loads(
                        match.group(1) if match.lastindex else match.group(0)
                    )
                except json.JSONDecodeError:
                    continue

        logger.warning(f"Failed to parse JSON from content: {content[:100]}")
        return None

    @staticmethod
    def parse_json_safe(content: str, default: Any = None) -> Any:
        """安全解析 JSON，失败时返回默认值"""
        result = ResponseParser.parse_json(content)
        return result if result is not None else default

    @staticmethod
    def _extract_content(response: Any) -> str:
        """提取响应内容"""
        try:
            if hasattr(response, "choices") and response.choices:
                message = response.choices[0].message
                if hasattr(message, "content") and message.content:
                    return message.content
                if hasattr(message, "function_call"):
                    return str(message.function_call)
            if hasattr(response, "content"):
                return response.content
            return str(response)
        except Exception as e:
            logger.error(f"Failed to extract content: {e}")
            return str(response)

    @staticmethod
    def _extract_tool_calls(response: Any) -> Optional[List[Dict]]:
        """提取工具调用（function calling）"""
        try:
            if hasattr(response, "choices") and response.choices:
                message = response.choices[0].message
                if hasattr(message, "tool_calls") and message.tool_calls:
                    return [
                        {
                            "id": tc.id,
                            "name": tc.function.name,
                            "arguments": json.loads(tc.function.arguments)
                            if tc.function.arguments
                            else {},
                        }
                        for tc in message.tool_calls
                    ]
            return None
        except Exception as e:
            logger.error(f"Failed to extract tool calls: {e}")
            return None

    @staticmethod
    def _extract_usage(response: Any) -> Optional[Dict]:
        """提取 Token 使用统计"""
        try:
            if hasattr(response, "usage"):
                return {
                    "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(
                        response.usage, "completion_tokens", 0
                    ),
                    "total_tokens": getattr(response.usage, "total_tokens", 0),
                }
            return None
        except Exception as e:
            logger.error(f"Failed to extract usage: {e}")
            return None
