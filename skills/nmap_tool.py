"""Nmap Skill - 端口扫描工具作为Skill使用"""

from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type
import subprocess


class NmapScanInput(BaseModel):
    """Nmap扫描输入参数"""
    target: str = Field(description="目标主机 IP或域名")
    ports: str = Field(default=None, description="端口范围，如 '1-1000' 或 '80,443,8080'")
    scan_type: str = Field(default="-sV", description="扫描类型: -sV版本检测, -sS SYN扫描, -sT TCP扫描")
    extra_args: str = Field(default="", description="额外参数")


class NmapTool(BaseTool):
    """Nmap端口扫描工具"""
    
    name: str = "nmap_port_scanner"
    description: str = "执行Nmap端口扫描，用于发现目标主机的开放端口和服务信息。这是渗透测试信息收集阶段的核心工具。必填参数: target(目标)"
    args_schema: Type[BaseModel] = NmapScanInput

    def _run(self, target: str, ports: str = None, scan_type: str = "-sV", extra_args: str = "") -> str:
        """执行Nmap扫描"""
        if not target:
            return "错误: 请提供目标主机"
        
        cmd = ["nmap"]
        
        if scan_type:
            cmd.append(scan_type)
        
        if ports:
            cmd.extend(["-p", ports])
        
        if extra_args:
            cmd.extend(extra_args.split())
        
        cmd.append(target)
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300
            )
            
            output = result.stdout if result.stdout else result.stderr
            
            return self._parse_nmap_output(output)
            
        except subprocess.TimeoutExpired:
            return "错误: 扫描超时，请尝试减少端口范围"
        except FileNotFoundError:
            return "错误: nmap未安装，请先安装nmap"
        except Exception as e:
            return f"错误: 扫描失败 - {str(e)}"

    def _parse_nmap_output(self, output: str) -> str:
        """解析Nmap输出"""
        if not output:
            return "无输出结果"
        
        lines = output.split('\n')
        result_lines = []
        result_lines.append("=" * 60)
        result_lines.append("Nmap 扫描结果")
        result_lines.append("=" * 60)
        
        open_ports = []
        
        for line in lines:
            if '/open/' in line or '/tcp/' in line or '/udp/' in line:
                open_ports.append(line.strip())
        
        if open_ports:
            result_lines.append("\n发现开放端口:")
            result_lines.append("-" * 40)
            for port in open_ports:
                result_lines.append(port)
        
        for line in lines:
            if 'PORT' in line or 'STATE' in line or 'SERVICE' in line or 'VERSION' in line:
                result_lines.append(line.strip())
        
        result_lines.append("-" * 40)
        result_lines.append("\n原始输出:")
        result_lines.append(output)
        
        return '\n'.join(result_lines)


class QuickNmapTool(BaseTool):
    """快速Nmap扫描 - 默认扫描常用端口"""
    
    name: str = "quick_nmap_scan"
    description: str = "快速扫描目标主机的常用端口，适合初步信息收集。必填参数: target(目标)"
    
    def _run(self, target: str) -> str:
        """快速扫描常用端口"""
        if not target:
            return "错误: 请提供目标主机"
        
        ports = "21,22,23,25,53,80,110,143,443,445,3306,3389,5432,8080,8443"
        
        cmd = ["nmap", "-sV", "-p", ports, "-T4", target]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120
            )
            
            output = result.stdout if result.stdout else result.stderr
            
            return output
            
        except subprocess.TimeoutExpired:
            return "错误: 扫描超时"
        except FileNotFoundError:
            return "错误: nmap未安装"
        except Exception as e:
            return f"错误: {str(e)}"


class FullNmapTool(BaseTool):
    """全面Nmap扫描 - 包含操作系统检测和漏洞脚本"""
    
    name: str = "full_nmap_scan"
    description: str = "对目标进行全面扫描，包括操作系统检测和漏洞脚本扫描。必填参数: target(目标)"
    
    def _run(self, target: str) -> str:
        """全面扫描"""
        if not target:
            return "错误: 请提供目标主机"
        
        cmd = ["nmap", "-sSV", "-O", "--script=vuln", target]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600
            )
            
            output = result.stdout if result.stdout else result.stderr
            
            return output
            
        except subprocess.TimeoutExpired:
            return "错误: 扫描超时(全面扫描可能需要较长时间)"
        except FileNotFoundError:
            return "错误: nmap未安装"
        except Exception as e:
            return f"错误: {str(e)}"


nmap_tool = NmapTool()
quick_nmap_tool = QuickNmapTool()
full_nmap_tool = FullNmapTool()
