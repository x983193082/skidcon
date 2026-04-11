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

    @classmethod
    def parse(
        cls, response: Any, expected_format: Optional[ResponseFormat] = None
    ) -> LLMResponse:
        """
        解析 LLM 响应

        Args:
            response: 原始响应对象
            expected_format: 期望的格式（若为 None 则自动检测）

        Returns:
            LLMResponse 对象
        """
        content = cls._extract_content(response)
        tool_calls = cls._extract_tool_calls(response)
        usage = cls._extract_usage(response)

        # 自动检测格式
        if expected_format is None:
            detected_format = cls._detect_format(content)
        else:
            detected_format = expected_format

        return LLMResponse(
            content=content,
            format=detected_format,
            raw_response=response,
            tool_calls=tool_calls,
            usage=usage,
        )

    @classmethod
    def _detect_format(cls, content: str) -> ResponseFormat:
        """自动检测内容格式"""
        content = content.strip()
        if not content:
            return ResponseFormat.PLAIN

        # 尝试解析 JSON（不依赖正则，直接 json.loads）
        try:
            json.loads(content)
            return ResponseFormat.JSON
        except json.JSONDecodeError:
            pass

        # 检查是否包含 Markdown 标记
        if re.search(r"```|^#|^\*|\[.+\]\(.+\)", content, re.MULTILINE):
            return ResponseFormat.MARKDOWN

        return ResponseFormat.PLAIN

    @classmethod
    def parse_json(cls, content: str) -> Optional[Dict]:
        """
        解析 JSON 内容
        支持：
        1. 直接 JSON 字符串
        2. Markdown 代码块中的 JSON（```json ... ``` 或 ``` ... ```）
        3. 从文本中提取最外层的 JSON 对象（支持嵌套）
        """
        if not content:
            return None

        content = content.strip()

        # 1. 直接解析整个字符串
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # 2. 提取 Markdown 代码块
        patterns = [
            r"```json\s*(.*?)\s*```",  # ```json ... ```
            r"```\s*(.*?)\s*```",  # ``` ... ```
        ]

        for pattern in patterns:
            match = re.search(pattern, content, re.DOTALL)
            if match:
                code_content = match.group(1).strip()
                try:
                    return json.loads(code_content)
                except json.JSONDecodeError:
                    continue

        # 3. 从文本中提取 JSON 对象（支持嵌套）
        # 寻找第一个 '{' 和对应的 '}'
        start = content.find("{")
        if start == -1:
            logger.warning("No JSON object found in content")
            return None

        # 使用括号计数找到匹配的结束大括号
        count = 0
        in_string = False
        escape = False
        for i in range(start, len(content)):
            ch = content[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"' and not escape:
                in_string = not in_string
            if not in_string:
                if ch == "{":
                    count += 1
                elif ch == "}":
                    count -= 1
                    if count == 0:
                        end = i
                        json_str = content[start : end + 1]
                        try:
                            return json.loads(json_str)
                        except json.JSONDecodeError:
                            logger.warning("Extracted JSON block is invalid")
                            return None

        logger.warning("Unbalanced braces, cannot extract complete JSON")
        return None

    @classmethod
    def parse_json_safe(cls, content: str, default: Any = None) -> Any:
        """安全解析 JSON，失败时返回默认值"""
        result = cls.parse_json(content)
        return result if result is not None else default

    @classmethod
    def _extract_content(cls, response: Any) -> str:
        """提取响应内容"""
        try:
            if hasattr(response, "choices") and response.choices:
                message = response.choices[0].message
                if hasattr(message, "content") and message.content is not None:
                    return message.content
                if hasattr(message, "function_call"):
                    return str(message.function_call)
            if hasattr(response, "content"):
                return response.content
            return str(response)
        except Exception as e:
            logger.error(f"Failed to extract content: {e}")
            return str(response)

    @classmethod
    def _extract_tool_calls(cls, response: Any) -> Optional[List[Dict]]:
        """提取工具调用（function calling）"""
        try:
            if hasattr(response, "choices") and response.choices:
                message = response.choices[0].message
                if hasattr(message, "tool_calls") and message.tool_calls:
                    tool_calls = []
                    for tc in message.tool_calls:
                        try:
                            args_str = tc.function.arguments or "{}"
                            arguments = json.loads(args_str)
                        except json.JSONDecodeError as e:
                            logger.warning(
                                f"Failed to parse tool arguments: {e}, using empty dict"
                            )
                            arguments = {}
                        tool_calls.append(
                            {
                                "id": getattr(tc, "id", None),
                                "name": tc.function.name,
                                "arguments": arguments,
                            }
                        )
                    return tool_calls
            return None
        except Exception as e:
            logger.error(f"Failed to extract tool calls: {e}")
            return None

    @classmethod
    def _extract_usage(cls, response: Any) -> Optional[Dict]:
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
