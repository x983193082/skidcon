"""
Tool Interface - 工具抽象基类
所有安全工具封装必须继承此类
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from enum import Enum


class ToolCategory(Enum):
    """工具类别枚举"""
    SCANNER = "scanner"          # 扫描类 (Nmap, Masscan)
    EXPLOIT = "exploit"          # 漏洞利用 (SQLMap, Metasploit)
    POST_EXPLOIT = "post_exploit"  # 后渗透
    RECON = "recon"              # 信息收集
    CUSTOM = "custom"            # 自定义脚本


class ToolRisk(Enum):
    """工具风险等级"""
    LOW = "low"          # 信息收集类
    MEDIUM = "medium"    # 扫描类
    HIGH = "high"        # 漏洞利用类
    CRITICAL = "critical"  # 高危操作


@dataclass
class ToolResult:
    """工具执行结果标准格式"""
    success: bool
    data: Dict[str, Any]
    error: Optional[str] = None
    raw_output: Optional[str] = None
    execution_time: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "raw_output": self.raw_output,
            "execution_time": self.execution_time
        }


class BaseTool(ABC):
    """
    工具抽象基类
    
    所有安全工具封装必须继承此类，实现：
    - execute: 执行工具
    - validate_params: 参数验证
    - parse_output: 输出解析
    """
    
    def __init__(
        self,
        name: str,
        category: ToolCategory,
        description: str = "",
        risk_level: ToolRisk = ToolRisk.LOW,
        version: str = "1.0.0"
    ):
        self.name = name
        self.category = category
        self.description = description
        self.risk_level = risk_level
        self.version = version
        self._last_result: Optional[ToolResult] = None
    
    @abstractmethod
    async def execute(self, target: str, params: Dict[str, Any] = None) -> ToolResult:
        """
        执行工具
        
        Args:
            target: 目标地址
            params: 工具参数
        
        Returns:
            ToolResult对象
        """
        pass
    
    @abstractmethod
    def validate_params(self, params: Dict[str, Any]) -> bool:
        """
        验证参数有效性
        
        Args:
            params: 工具参数字典
        
        Returns:
            参数是否有效
        """
        pass
    
    @abstractmethod
    def parse_output(self, raw_output: str) -> Dict[str, Any]:
        """
        解析工具原始输出
        
        Args:
            raw_output: 工具原始输出字符串
        
        Returns:
            解析后的结构化数据
        """
        pass
    
    def get_info(self) -> Dict[str, Any]:
        """获取工具信息"""
        return {
            "name": self.name,
            "category": self.category.value,
            "description": self.description,
            "risk_level": self.risk_level.value,
            "version": self.version
        }
    
    def get_last_result(self) -> Optional[ToolResult]:
        """获取最近一次执行结果"""
        return self._last_result
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name='{self.name}' category={self.category.value}>"
