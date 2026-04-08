"""
SQLMap Wrapper - SQL注入检测工具封装
"""
from typing import Dict, Any, List, Optional
from ..core.tool_interface import BaseTool, ToolCategory, ToolRisk, ToolResult
import asyncio


class SQLMapWrapper(BaseTool):
    """
    SQLMap工具封装
    
    自动化SQL注入检测和利用
    """
    
    # 风险等级配置
    RISK_LEVELS = {
        "low": "--risk=1 --level=1",
        "medium": "--risk=2 --level=2",
        "high": "--risk=3 --level=3"
    }
    
    def __init__(self, sqlmap_path: str = "sqlmap"):
        super().__init__(
            name="sqlmap",
            category=ToolCategory.EXPLOIT,
            description="Automatic SQL injection detection and exploitation",
            risk_level=ToolRisk.HIGH,
            version="1.0.0"
        )
        self.sqlmap_path = sqlmap_path
    
    async def execute(self, target: str, params: Dict[str, Any] = None) -> ToolResult:
        """
        执行SQLMap
        
        Args:
            target: 目标URL
            params: 参数配置
                - data: POST数据
                - cookies: Cookie
                - headers: 自定义头
                - risk: 风险等级
                - technique: 注入技术
        
        Returns:
            ToolResult对象
        """
        import time
        start_time = time.time()
        
        params = params or {}
        
        if not self.validate_params(params):
            return ToolResult(
                success=False,
                data={},
                error="Invalid parameters",
                execution_time=0
            )
        
        try:
            cmd = self._build_command(target, params)
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            raw_output = stdout.decode('utf-8', errors='ignore')
            parsed_data = self.parse_output(raw_output)
            
            execution_time = time.time() - start_time
            
            result = ToolResult(
                success=process.returncode == 0,
                data=parsed_data,
                error=stderr.decode('utf-8') if stderr else None,
                raw_output=raw_output,
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
    
    def _build_command(self, target: str, params: Dict[str, Any]) -> List[str]:
        """构建SQLMap命令"""
        cmd = [
            "python", self.sqlmap_path,
            "-u", target,
            "--batch",  # 非交互模式
            "--random-agent"
        ]
        
        # POST数据
        if "data" in params:
            cmd.extend(["--data", params["data"]])
        
        # Cookies
        if "cookies" in params:
            cmd.extend(["--cookie", params["cookies"]])
        
        # 自定义头
        if "headers" in params:
            for key, value in params["headers"].items():
                cmd.extend(["--header", f"{key}: {value}"])
        
        # 风险等级
        risk = params.get("risk", "low")
        if risk in self.RISK_LEVELS:
            cmd.extend(self.RISK_LEVELS[risk].split())
        
        # 注入技术
        if "technique" in params:
            cmd.extend(["--technique", params["technique"]])
        
        return cmd
    
    def validate_params(self, params: Dict[str, Any]) -> bool:
        """验证参数"""
        if not params:
            return True
        
        risk = params.get("risk")
        if risk and risk not in self.RISK_LEVELS:
            return False
        
        return True
    
    def parse_output(self, raw_output: str) -> Dict[str, Any]:
        """解析SQLMap输出"""
        result = {
            "vulnerable": False,
            "injection_points": [],
            "databases": [],
            "tables": [],
            "columns": []
        }
        
        lines = raw_output.split('\n')
        
        for line in lines:
            # 检测是否存在注入
            if "appears to be injectable" in line.lower():
                result["vulnerable"] = True
            
            # 解析注入点
            if "Parameter:" in line:
                parts = line.split(":")
                if len(parts) >= 2:
                    result["injection_points"].append({
                        "parameter": parts[1].strip(),
                        "type": "injection"
                    })
        
        return result
    
    async def test_url(self, url: str) -> ToolResult:
        """测试URL是否存在SQL注入"""
        return await self.execute(url, {"risk": "low"})
    
    async def get_databases(self, url: str) -> ToolResult:
        """获取数据库列表"""
        return await self.execute(url, {
            "risk": "medium",
            "extra_args": "--dbs"
        })
    
    async def get_tables(self, url: str, database: str) -> ToolResult:
        """获取指定数据库的表"""
        return await self.execute(url, {
            "risk": "medium",
            "extra_args": f"-D {database} --tables"
        })