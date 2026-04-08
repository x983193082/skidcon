"""
测试工具接口
"""
import pytest
from src.core.tool_interface import BaseTool, ToolCategory, ToolRisk, ToolResult


class TestToolInterface:
    """测试工具接口"""
    
    def test_tool_category_enum(self):
        """测试工具类别枚举"""
        assert ToolCategory.SCANNER.value == "scanner"
        assert ToolCategory.EXPLOIT.value == "exploit"
        assert ToolCategory.RECON.value == "recon"
    
    def test_tool_risk_enum(self):
        """测试工具风险等级枚举"""
        assert ToolRisk.LOW.value == "low"
        assert ToolRisk.MEDIUM.value == "medium"
        assert ToolRisk.HIGH.value == "high"
        assert ToolRisk.CRITICAL.value == "critical"
    
    def test_tool_result_dataclass(self):
        """测试ToolResult数据类"""
        result = ToolResult(
            success=True,
            output="Test output",
            error=None,
            metadata={"key": "value"}
        )
        
        assert result.success is True
        assert result.output == "Test output"
        assert result.error is None
    
    def test_base_tool_initialization(self):
        """测试BaseTool初始化"""
        class MockTool(BaseTool):
            async def execute(self, params: dict) -> ToolResult:
                return ToolResult(success=True, output="OK")
            
            def validate_params(self, params: dict) -> bool:
                return True
            
            def parse_output(self, raw_output: str) -> dict:
                return {}
        
        tool = MockTool(
            name="TestTool",
            category=ToolCategory.SCANNER,
            description="Test tool",
            risk_level=ToolRisk.LOW
        )
        
        assert tool.name == "TestTool"
        assert tool.category == ToolCategory.SCANNER
        assert tool.risk_level == ToolRisk.LOW