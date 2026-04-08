"""
Custom POC - 自定义POC脚本封装
"""
from typing import Dict, Any, List, Optional, Callable
from ..core.tool_interface import BaseTool, ToolCategory, ToolRisk, ToolResult
from dataclasses import dataclass
import asyncio


@dataclass
class POCInfo:
    """POC信息"""
    name: str
    vuln_type: str
    description: str
    author: str
    references: List[str]
    severity: str


class CustomPOC(BaseTool):
    """
    自定义POC脚本封装
    
    支持加载和执行自定义漏洞验证脚本
    """
    
    def __init__(
        self,
        name: str,
        poc_info: POCInfo,
        verify_func: Callable,
        exploit_func: Optional[Callable] = None
    ):
        super().__init__(
            name=name,
            category=ToolCategory.CUSTOM,
            description=poc_info.description,
            risk_level=ToolRisk.HIGH if exploit_func else ToolRisk.MEDIUM,
            version="1.0.0"
        )
        self.poc_info = poc_info
        self._verify_func = verify_func
        self._exploit_func = exploit_func
    
    async def execute(self, target: str, params: Dict[str, Any] = None) -> ToolResult:
        """
        执行POC验证
        
        Args:
            target: 目标地址
            params: 参数
                - mode: verify/exploit
                - 其他自定义参数
        
        Returns:
            ToolResult对象
        """
        import time
        start_time = time.time()
        
        params = params or {}
        mode = params.get("mode", "verify")
        
        try:
            if mode == "exploit" and self._exploit_func:
                result_data = await self._run_exploit(target, params)
            else:
                result_data = await self._run_verify(target, params)
            
            execution_time = time.time() - start_time
            
            result = ToolResult(
                success=result_data.get("vulnerable", False),
                data=result_data,
                execution_time=execution_time
            )
            
            self._last_result = result
            return result
            
        except Exception as e:
            return ToolResult(
                success=False,
                data={},
                error=str(e),
                execution_time=time.time() - start_time
            )
    
    async def _run_verify(self, target: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """运行验证函数"""
        if asyncio.iscoroutinefunction(self._verify_func):
            return await self._verify_func(target, **params)
        return self._verify_func(target, **params)
    
    async def _run_exploit(self, target: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """运行利用函数"""
        if self._exploit_func is None:
            return {"vulnerable": False, "error": "No exploit function"}
        
        if asyncio.iscoroutinefunction(self._exploit_func):
            return await self._exploit_func(target, **params)
        return self._exploit_func(target, **params)
    
    def validate_params(self, params: Dict[str, Any]) -> bool:
        """验证参数"""
        return True
    
    def parse_output(self, raw_output: str) -> Dict[str, Any]:
        """解析输出（POC直接返回结构化数据）"""
        return {}
    
    def get_poc_info(self) -> Dict[str, Any]:
        """获取POC信息"""
        return {
            "name": self.poc_info.name,
            "vuln_type": self.poc_info.vuln_type,
            "description": self.poc_info.description,
            "author": self.poc_info.author,
            "references": self.poc_info.references,
            "severity": self.poc_info.severity,
            "has_exploit": self._exploit_func is not None
        }


class POCRegistry:
    """POC注册表"""
    
    def __init__(self):
        self._pocs: Dict[str, CustomPOC] = {}
    
    def register(self, poc: CustomPOC) -> None:
        """注册POC"""
        self._pocs[poc.name] = poc
    
    def get(self, name: str) -> Optional[CustomPOC]:
        """获取POC"""
        return self._pocs.get(name)
    
    def list_pocs(self) -> List[str]:
        """列出所有POC"""
        return list(self._pocs.keys())
    
    def get_by_vuln_type(self, vuln_type: str) -> List[CustomPOC]:
        """根据漏洞类型获取POC"""
        return [
            poc for poc in self._pocs.values()
            if poc.poc_info.vuln_type == vuln_type
        ]


# 全局POC注册表
poc_registry = POCRegistry()


def register_poc(
    name: str,
    vuln_type: str,
    description: str,
    author: str = "unknown",
    references: List[str] = None,
    severity: str = "medium"
):
    """
    POC注册装饰器
    
    使用示例:
    @register_poc(
        name="sqli_basic",
        vuln_type="sqli",
        description="Basic SQL injection test"
    )
    async def verify_sqli(target, **kwargs):
        # 验证逻辑
        return {"vulnerable": True, "evidence": "..."}
    """
    def decorator(func: Callable):
        poc_info = POCInfo(
            name=name,
            vuln_type=vuln_type,
            description=description,
            author=author,
            references=references or [],
            severity=severity
        )
        poc = CustomPOC(name=name, poc_info=poc_info, verify_func=func)
        poc_registry.register(poc)
        return func
    return decorator