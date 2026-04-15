"""
Nmap Wrapper - Nmap扫描工具封装
"""
from typing import Dict, Any, List, Optional
from ..core.tool_interface import BaseTool, ToolCategory, ToolRisk, ToolResult
import asyncio
import subprocess
import xml.etree.ElementTree as ET
from loguru import logger


class NmapWrapper(BaseTool):
    """
    Nmap扫描工具封装
    
    支持多种扫描模式：
    - 快速扫描
    - 全端口扫描
    - 服务版本检测
    - 漏洞脚本扫描
    """
    
    # 常用扫描配置
    SCAN_PROFILES = {
        "quick": "-T4 -F",
        "full": "-T4 -p-",
        "service": "-T4 -sV -sC",
        "vuln": "-T4 --script vuln",
        "udp": "-T4 -sU --top-ports 100",
        "stealth": "-T2 -sS -f"
    }
    
    def __init__(self, nmap_path: str = "nmap"):
        super().__init__(
            name="nmap",
            category=ToolCategory.SCANNER,
            description="Network exploration and security auditing tool",
            risk_level=ToolRisk.MEDIUM,
            version="1.0.0"
        )
        self.nmap_path = nmap_path
    
    async def execute(self, target: str, params: Dict[str, Any] = None) -> ToolResult:
        """
        执行Nmap扫描
        
        Args:
            target: 目标地址（IP/域名/网段）
            params: 扫描参数
                - profile: 扫描配置名称
                - ports: 指定端口
                - script: NSE脚本
                - extra_args: 额外参数
        
        Returns:
            ToolResult对象
        """
        import time
        start_time = time.time()
        
        params = params or {}
        
        # 验证参数
        if not self.validate_params(params):
            return ToolResult(
                success=False,
                data={},
                error="Invalid parameters",
                execution_time=0
            )
        
        try:
            # 构建命令
            cmd = self._build_command(target, params)
            
            # 执行扫描
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            raw_output = stdout.decode('utf-8', errors='ignore')
            
            # 解析结果
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
        """构建Nmap命令"""
        cmd = [self.nmap_path]
        
        # 添加扫描配置
        profile = params.get("profile", "quick")
        if profile in self.SCAN_PROFILES:
            cmd.extend(self.SCAN_PROFILES[profile].split())
        
        # 指定端口
        if "ports" in params:
            cmd.extend(["-p", str(params["ports"])])
        
        # NSE脚本
        if "script" in params:
            cmd.extend(["--script", params["script"]])
        
        # 额外参数
        if "extra_args" in params:
            cmd.extend(params["extra_args"].split())
        
        # 输出格式
        cmd.extend(["-oX", "-"])  # XML输出到stdout
        
        # 目标
        cmd.append(target)
        
        return cmd
    
    def validate_params(self, params: Dict[str, Any]) -> bool:
        """验证参数有效性"""
        if not params:
            return True
        
        # 检查profile是否有效
        profile = params.get("profile")
        if profile and profile not in self.SCAN_PROFILES:
            return False
        
        return True
    
    def parse_output(self, raw_output: str) -> Dict[str, Any]:
        """解析Nmap输出"""
        result = {
            "hosts": [],
            "summary": {
                "total_hosts": 0,
                "up_hosts": 0,
                "down_hosts": 0
            }
        }
        
        # 简单的文本解析（实际应使用XML解析）
        lines = raw_output.split('\n')
        
        current_host = None
        for line in lines:
            line = line.strip()
            
            # 解析主机状态
            if "Nmap scan report for" in line:
                if current_host:
                    result["hosts"].append(current_host)
                current_host = {
                    "address": line.split()[-1],
                    "ports": [],
                    "os": None
                }
            
            # 解析端口
            elif current_host and "/tcp" in line or "/udp" in line:
                parts = line.split()
                if len(parts) >= 3:
                    port_info = parts[0].split("/")
                    current_host["ports"].append({
                        "port": int(port_info[0]),
                        "protocol": port_info[1],
                        "state": parts[1],
                        "service": parts[2] if len(parts) > 2 else "unknown"
                    })
        
        if current_host:
            result["hosts"].append(current_host)
        
        result["summary"]["total_hosts"] = len(result["hosts"])
        result["summary"]["up_hosts"] = len([h for h in result["hosts"] if h.get("ports")])
        
        return result
    
    def parse_xml(self, xml_output: str) -> Dict[str, Any]:
        """解析Nmap XML输出"""
        result = {
            "hosts": [],
            "summary": {
                "total_hosts": 0,
                "up_hosts": 0,
                "down_hosts": 0
            }
        }
        
        try:
            root = ET.fromstring(xml_output)
        except ET.ParseError as e:
            logger.error(f"Failed to parse Nmap XML: {e}")
            return result
        
        for host_elem in root.findall("host"):
            host_info = {
                "address": "",
                "status": "unknown",
                "ports": [],
                "os": None,
                "hostnames": []
            }
            
            # 解析主机状态
            status_elem = host_elem.find("status")
            if status_elem is not None:
                host_info["status"] = status_elem.get("state", "unknown")
            
            # 解析地址
            for addr_elem in host_elem.findall("address"):
                addr_type = addr_elem.get("addrtype", "ipv4")
                if addr_type == "ipv4":
                    host_info["address"] = addr_elem.get("addr", "")
            
            # 解析主机名
            for hostname_elem in host_elem.findall("hostnames/hostname"):
                host_info["hostnames"].append({
                    "name": hostname_elem.get("name", ""),
                    "type": hostname_elem.get("type", "")
                })
            
            # 解析端口
            for port_elem in host_elem.findall("ports/port"):
                port_id = port_elem.get("portid")
                protocol = port_elem.get("protocol", "tcp")
                
                state_elem = port_elem.find("state")
                state = state_elem.get("state", "unknown") if state_elem is not None else "unknown"
                
                service_elem = port_elem.find("service")
                service_info = {
                    "name": "unknown",
                    "product": "",
                    "version": "",
                    "extrainfo": ""
                }
                if service_elem is not None:
                    service_info["name"] = service_elem.get("name", "unknown")
                    service_info["product"] = service_elem.get("product", "")
                    service_info["version"] = service_elem.get("version", "")
                    service_info["extrainfo"] = service_elem.get("extrainfo", "")
                
                host_info["ports"].append({
                    "port": int(port_id) if port_id else 0,
                    "protocol": protocol,
                    "state": state,
                    "service": service_info["name"],
                    "product": service_info["product"],
                    "version": service_info["version"],
                    "extrainfo": service_info["extrainfo"]
                })
            
            # 解析操作系统
            os_elem = host_elem.find("os/osmatch")
            if os_elem is not None:
                host_info["os"] = {
                    "name": os_elem.get("name", ""),
                    "accuracy": float(os_elem.get("accuracy", 0))
                }
            
            if host_info["address"]:
                result["hosts"].append(host_info)
        
        result["summary"]["total_hosts"] = len(result["hosts"])
        result["summary"]["up_hosts"] = len([h for h in result["hosts"] if h.get("status") == "up"])
        result["summary"]["down_hosts"] = result["summary"]["total_hosts"] - result["summary"]["up_hosts"]
        
        return result
        # TODO: 实现完整的XML解析
        pass
    
    async def quick_scan(self, target: str) -> ToolResult:
        """快速扫描"""
        return await self.execute(target, {"profile": "quick"})
    
    async def full_scan(self, target: str) -> ToolResult:
        """全端口扫描"""
        return await self.execute(target, {"profile": "full"})
    
    async def service_scan(self, target: str) -> ToolResult:
        """服务版本扫描"""
        return await self.execute(target, {"profile": "service"})
    
    async def vuln_scan(self, target: str) -> ToolResult:
        """漏洞脚本扫描"""
        return await self.execute(target, {"profile": "vuln"})