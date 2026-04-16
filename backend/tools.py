"""
SkidCon Kali 工具封装模块
封装 50+ 渗透测试工具，提供统一的异步执行接口
"""

import asyncio
import re
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
from config import TASK_TIMEOUT


@dataclass
class ToolResult:
    """工具执行结果"""
    tool_name: str
    command: str
    stdout: str
    stderr: str
    returncode: int
    success: bool
    parsed_data: Optional[Dict] = None


class KaliTool:
    """Kali 工具基类"""
    
    def __init__(self, tool_name: str, command_template: str, timeout: int = TASK_TIMEOUT):
        self.tool_name = tool_name
        self.command_template = command_template
        self.timeout = timeout
    
    def build_command(self, **kwargs) -> str:
        """构建命令"""
        return self.command_template.format(**kwargs)
    
    async def execute(self, callback: Optional[Callable] = None, **kwargs) -> ToolResult:
        """异步执行工具"""
        command = self.build_command(**kwargs)
        
        if callback:
            await callback(f"[{self.tool_name}] 执行命令: {command}")
        
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout_data = []
            stderr_data = []
            
            async def read_stream(stream, data_list, prefix):
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    decoded = line.decode('utf-8', errors='ignore')
                    data_list.append(decoded)
                    if callback:
                        await callback(f"[{self.tool_name}] {prefix}: {decoded.strip()}")
            
            await asyncio.wait_for(
                asyncio.gather(
                    read_stream(process.stdout, stdout_data, "OUT"),
                    read_stream(process.stderr, stderr_data, "ERR")
                ),
                timeout=self.timeout
            )
            
            returncode = await process.wait()
            
            stdout = ''.join(stdout_data)
            stderr = ''.join(stderr_data)
            
            result = ToolResult(
                tool_name=self.tool_name,
                command=command,
                stdout=stdout,
                stderr=stderr,
                returncode=returncode,
                success=returncode == 0
            )
            
            # 解析输出
            result.parsed_data = self.parse_output(stdout, stderr)
            
            return result
            
        except asyncio.TimeoutError:
            process.kill()
            if callback:
                await callback(f"[{self.tool_name}] 执行超时")
            return ToolResult(
                tool_name=self.tool_name,
                command=command,
                stdout="",
                stderr="执行超时",
                returncode=-1,
                success=False
            )
        except Exception as e:
            if callback:
                await callback(f"[{self.tool_name}] 执行错误: {str(e)}")
            return ToolResult(
                tool_name=self.tool_name,
                command=command,
                stdout="",
                stderr=str(e),
                returncode=-1,
                success=False
            )
    
    def parse_output(self, stdout: str, stderr: str) -> Optional[Dict]:
        """解析工具输出，子类可重写"""
        return {"raw_output": stdout}


# ==================== 扫描类工具 ====================

class NmapTool(KaliTool):
    """Nmap 端口扫描器"""
    def __init__(self):
        super().__init__("nmap", "nmap -sV -sC -O -oN - {target}")
    
    def parse_output(self, stdout, stderr):
        ports = []
        for line in stdout.split('\n'):
            match = re.match(r'(\d+/\w+)\s+(\w+)\s+(\w+)\s+(.*)', line)
            if match:
                ports.append({
                    "port": match.group(1),
                    "state": match.group(2),
                    "service": match.group(3),
                    "version": match.group(4)
                })
        return {"ports": ports, "raw_output": stdout}


class MasscanTool(KaliTool):
    """Masscan 快速端口扫描器"""
    def __init__(self):
        super().__init__("masscan", "masscan -p1-65535 {target} --rate=1000")
    
    def parse_output(self, stdout, stderr):
        ports = []
        for line in stdout.split('\n'):
            match = re.match(r'Discovered open port (\d+)/tcp on (.*)', line)
            if match:
                ports.append({"port": match.group(1), "ip": match.group(2)})
        return {"ports": ports, "raw_output": stdout}


class RustscanTool(KaliTool):
    """Rustscan 快速端口扫描器"""
    def __init__(self):
        super().__init__("rustscan", "rustscan -a {target} -- -sV")
    
    def parse_output(self, stdout, stderr):
        return {"raw_output": stdout}


class NaabuTool(KaliTool):
    """Naabu 端口扫描器"""
    def __init__(self):
        super().__init__("naabu", "naabu -host {target} -nmap-cli 'nmap -sV'")
    
    def parse_output(self, stdout, stderr):
        return {"raw_output": stdout}


# ==================== Web 类工具 ====================

class SqlmapTool(KaliTool):
    """SQLMap SQL 注入检测"""
    def __init__(self):
        super().__init__("sqlmap", "sqlmap -u {url} --batch --level=3 --risk=2")
    
    def parse_output(self, stdout, stderr):
        vulnerable = "is vulnerable" in stdout.lower()
        return {"vulnerable": vulnerable, "raw_output": stdout}


class GobusterTool(KaliTool):
    """Gobuster 目录爆破"""
    def __init__(self):
        super().__init__("gobuster", "gobuster dir -u {url} -w {wordlist} -t 20")
    
    def parse_output(self, stdout, stderr):
        dirs = []
        for line in stdout.split('\n'):
            if line.startswith("Found:"):
                dirs.append(line.replace("Found:", "").strip())
        return {"directories": dirs, "raw_output": stdout}


class DirbTool(KaliTool):
    """Dirb 目录扫描"""
    def __init__(self):
        super().__init__("dirb", "dirb {url} {wordlist}")
    
    def parse_output(self, stdout, stderr):
        return {"raw_output": stdout}


class FfufTool(KaliTool):
    """Ffuf 模糊测试"""
    def __init__(self):
        super().__init__("ffuf", "ffuf -u {url}/FUZZ -w {wordlist} -mc 200,301,302,403")
    
    def parse_output(self, stdout, stderr):
        return {"raw_output": stdout}


class NiktoTool(KaliTool):
    """Nikto Web 漏洞扫描"""
    def __init__(self):
        super().__init__("nikto", "nikto -h {url}")
    
    def parse_output(self, stdout, stderr):
        vulns = []
        for line in stdout.split('\n'):
            if line.startswith("+ OSVDB"):
                vulns.append(line.strip())
        return {"vulnerabilities": vulns, "raw_output": stdout}


class WpscanTool(KaliTool):
    """WPScan WordPress 扫描"""
    def __init__(self):
        super().__init__("wpscan", "wpscan --url {url} --random-user-agent")
    
    def parse_output(self, stdout, stderr):
        return {"raw_output": stdout}


class JoomscanTool(KaliTool):
    """Joomscan Joomla 扫描"""
    def __init__(self):
        super().__init__("joomscan", "joomscan -u {url}")
    
    def parse_output(self, stdout, stderr):
        return {"raw_output": stdout}


# ==================== 漏洞利用工具 ====================

class SearchsploitTool(KaliTool):
    """Searchsploit 漏洞搜索"""
    def __init__(self):
        super().__init__("searchsploit", "searchsploit {query}")
    
    def parse_output(self, stdout, stderr):
        exploits = []
        lines = stdout.split('\n')
        for line in lines[3:]:  # 跳过标题行
            if line.strip() and '|' in line:
                parts = line.split('|')
                if len(parts) >= 2:
                    exploits.append({
                        "title": parts[0].strip(),
                        "path": parts[-1].strip()
                    })
        return {"exploits": exploits, "raw_output": stdout}


class NucleiTool(KaliTool):
    """Nuclei 漏洞扫描"""
    def __init__(self):
        super().__init__("nuclei", "nuclei -u {url} -t cves/ -json")
    
    def parse_output(self, stdout, stderr):
        vulns = []
        for line in stdout.split('\n'):
            if line.strip():
                try:
                    import json
                    vulns.append(json.loads(line))
                except:
                    pass
        return {"vulnerabilities": vulns, "raw_output": stdout}


class MetasploitTool(KaliTool):
    """Metasploit 漏洞利用框架"""
    def __init__(self):
        super().__init__("msfconsole", "msfconsole -q -x 'use {module}; set RHOSTS {target}; run; exit'")
    
    def parse_output(self, stdout, stderr):
        return {"raw_output": stdout}


# ==================== 信息收集工具 ====================

class WhoisTool(KaliTool):
    """Whois 域名查询"""
    def __init__(self):
        super().__init__("whois", "whois {domain}")
    
    def parse_output(self, stdout, stderr):
        return {"raw_output": stdout}


class DigTool(KaliTool):
    """Dig DNS 查询"""
    def __init__(self):
        super().__init__("dig", "dig {domain} ANY")
    
    def parse_output(self, stdout, stderr):
        records = []
        for line in stdout.split('\n'):
            if line.strip() and not line.startswith(';'):
                records.append(line.strip())
        return {"records": records, "raw_output": stdout}


class NslookupTool(KaliTool):
    """Nslookup DNS 查询"""
    def __init__(self):
        super().__init__("nslookup", "nslookup {domain}")
    
    def parse_output(self, stdout, stderr):
        return {"raw_output": stdout}


class HostTool(KaliTool):
    """Host DNS 查询"""
    def __init__(self):
        super().__init__("host", "host -a {domain}")
    
    def parse_output(self, stdout, stderr):
        return {"raw_output": stdout}


class TheHarvesterTool(KaliTool):
    """TheHarvester 信息收集"""
    def __init__(self):
        super().__init__("theharvester", "theHarvester -d {domain} -b all")
    
    def parse_output(self, stdout, stderr):
        return {"raw_output": stdout}


class AmassTool(KaliTool):
    """Amass 子域名枚举"""
    def __init__(self):
        super().__init__("amass", "amass enum -d {domain}")
    
    def parse_output(self, stdout, stderr):
        subdomains = [line.strip() for line in stdout.split('\n') if line.strip()]
        return {"subdomains": subdomains, "raw_output": stdout}


class SubfinderTool(KaliTool):
    """Subfinder 子域名发现"""
    def __init__(self):
        super().__init__("subfinder", "subfinder -d {domain}")
    
    def parse_output(self, stdout, stderr):
        subdomains = [line.strip() for line in stdout.split('\n') if line.strip()]
        return {"subdomains": subdomains, "raw_output": stdout}


class AssetfinderTool(KaliTool):
    """Assetfinder 资产发现"""
    def __init__(self):
        super().__init__("assetfinder", "assetfinder {domain}")
    
    def parse_output(self, stdout, stderr):
        assets = [line.strip() for line in stdout.split('\n') if line.strip()]
        return {"assets": assets, "raw_output": stdout}


class DnsreconTool(KaliTool):
    """Dnsrecon DNS 侦察"""
    def __init__(self):
        super().__init__("dnsrecon", "dnsrecon -d {domain}")
    
    def parse_output(self, stdout, stderr):
        return {"raw_output": stdout}


class DnsenumTool(KaliTool):
    """Dnsenum DNS 枚举"""
    def __init__(self):
        super().__init__("dnsenum", "dnsenum {domain}")
    
    def parse_output(self, stdout, stderr):
        return {"raw_output": stdout}


class WhatwebTool(KaliTool):
    """WhatWeb 技术识别"""
    def __init__(self):
        super().__init__("whatweb", "whatweb {url}")
    
    def parse_output(self, stdout, stderr):
        technologies = []
        for line in stdout.split('\n'):
            if line.strip():
                technologies.append(line.strip())
        return {"technologies": technologies, "raw_output": stdout}


# ==================== 服务枚举工具 ====================

class Enum4linuxTool(KaliTool):
    """Enum4linux SMB 枚举"""
    def __init__(self):
        super().__init__("enum4linux", "enum4linux {target}")
    
    def parse_output(self, stdout, stderr):
        return {"raw_output": stdout}


class SmbclientTool(KaliTool):
    """Smbclient SMB 客户端"""
    def __init__(self):
        super().__init__("smbclient", "smbclient -L //{target} -N")
    
    def parse_output(self, stdout, stderr):
        shares = []
        for line in stdout.split('\n'):
            if line.strip() and not line.startswith('Sharename'):
                shares.append(line.strip())
        return {"shares": shares, "raw_output": stdout}


class SnmpwalkTool(KaliTool):
    """Snmpwalk SNMP 查询"""
    def __init__(self):
        super().__init__("snmpwalk", "snmpwalk -v2c -c public {target}")
    
    def parse_output(self, stdout, stderr):
        return {"raw_output": stdout}


class OnesixtyoneTool(KaliTool):
    """Onesixtyone SNMP 扫描"""
    def __init__(self):
        super().__init__("onesixtyone", "onesixtyone {target}")
    
    def parse_output(self, stdout, stderr):
        return {"raw_output": stdout}


# ==================== 密码攻击工具 ====================

class HydraTool(KaliTool):
    """Hydra 密码爆破"""
    def __init__(self):
        super().__init__("hydra", "hydra -l {user} -P {wordlist} {target} {service}")
    
    def parse_output(self, stdout, stderr):
        credentials = []
        for line in stdout.split('\n'):
            if 'host:' in line and 'login:' in line:
                credentials.append(line.strip())
        return {"credentials": credentials, "raw_output": stdout}


class JohnTool(KaliTool):
    """John the Ripper 密码破解"""
    def __init__(self):
        super().__init__("john", "john --wordlist={wordlist} {hashfile}")
    
    def parse_output(self, stdout, stderr):
        return {"raw_output": stdout}


class HashcatTool(KaliTool):
    """Hashcat 密码破解"""
    def __init__(self):
        super().__init__("hashcat", "hashcat -m {mode} -a 0 {hashfile} {wordlist}")
    
    def parse_output(self, stdout, stderr):
        return {"raw_output": stdout}


class CrunchTool(KaliTool):
    """Crunch 密码字典生成"""
    def __init__(self):
        super().__init__("crunch", "crunch {min} {max} {charset}")
    
    def parse_output(self, stdout, stderr):
        return {"raw_output": stdout}


class CewlTool(KaliTool):
    """Cewl 自定义字典生成"""
    def __init__(self):
        super().__init__("cewl", "cewl -d 2 -m 5 {url}")
    
    def parse_output(self, stdout, stderr):
        words = [line.strip() for line in stdout.split('\n') if line.strip()]
        return {"words": words, "raw_output": stdout}


# ==================== 后渗透工具 ====================

class LinpeasTool(KaliTool):
    """LinPEAS Linux 权限枚举"""
    def __init__(self):
        super().__init__("linpeas", "bash {script_path}")
    
    def parse_output(self, stdout, stderr):
        return {"raw_output": stdout}


class WinpeasTool(KaliTool):
    """WinPEAS Windows 权限枚举"""
    def __init__(self):
        super().__init__("winpeas", "cmd /c {script_path}")
    
    def parse_output(self, stdout, stderr):
        return {"raw_output": stdout}


class LinenumTool(KaliTool):
    """LinEnum Linux 枚举"""
    def __init__(self):
        super().__init__("linenum", "bash {script_path}")
    
    def parse_output(self, stdout, stderr):
        return {"raw_output": stdout}


class LinuxExploitSuggesterTool(KaliTool):
    """Linux Exploit Suggester"""
    def __init__(self):
        super().__init__("linux-exploit-suggester", "bash {script_path}")
    
    def parse_output(self, stdout, stderr):
        exploits = []
        for line in stdout.split('\n'):
            if line.startswith('[+]'):
                exploits.append(line.strip())
        return {"exploits": exploits, "raw_output": stdout}


# ==================== 其他工具 ====================

class CurlTool(KaliTool):
    """Curl HTTP 客户端"""
    def __init__(self):
        super().__init__("curl", "curl -s -I {url}")
    
    def parse_output(self, stdout, stderr):
        headers = {}
        for line in stdout.split('\n'):
            if ': ' in line:
                key, value = line.split(': ', 1)
                headers[key.strip()] = value.strip()
        return {"headers": headers, "raw_output": stdout}


class WgetTool(KaliTool):
    """Wget 下载工具"""
    def __init__(self):
        super().__init__("wget", "wget -q -O - {url}")
    
    def parse_output(self, stdout, stderr):
        return {"raw_output": stdout}


class NcTool(KaliTool):
    """Netcat 网络工具"""
    def __init__(self):
        super().__init__("nc", "nc -zv {target} {port}")
    
    def parse_output(self, stdout, stderr):
        return {"raw_output": stdout}


class SocatTool(KaliTool):
    """Socat 网络中继"""
    def __init__(self):
        super().__init__("socat", "socat TCP-LISTEN:{lport} TCP:{target}:{rport}")
    
    def parse_output(self, stdout, stderr):
        return {"raw_output": stdout}


# ==================== 工具注册表 ====================

TOOL_REGISTRY = {
    # 扫描类
    "nmap": NmapTool,
    "masscan": MasscanTool,
    "rustscan": RustscanTool,
    "naabu": NaabuTool,
    
    # Web 类
    "sqlmap": SqlmapTool,
    "gobuster": GobusterTool,
    "dirb": DirbTool,
    "ffuf": FfufTool,
    "nikto": NiktoTool,
    "wpscan": WpscanTool,
    "joomscan": JoomscanTool,
    
    # 漏洞利用
    "searchsploit": SearchsploitTool,
    "nuclei": NucleiTool,
    "metasploit": MetasploitTool,
    
    # 信息收集
    "whois": WhoisTool,
    "dig": DigTool,
    "nslookup": NslookupTool,
    "host": HostTool,
    "theharvester": TheHarvesterTool,
    "amass": AmassTool,
    "subfinder": SubfinderTool,
    "assetfinder": AssetfinderTool,
    "dnsrecon": DnsreconTool,
    "dnsenum": DnsenumTool,
    "whatweb": WhatwebTool,
    
    # 服务枚举
    "enum4linux": Enum4linuxTool,
    "smbclient": SmbclientTool,
    "snmpwalk": SnmpwalkTool,
    "onesixtyone": OnesixtyoneTool,
    
    # 密码攻击
    "hydra": HydraTool,
    "john": JohnTool,
    "hashcat": HashcatTool,
    "crunch": CrunchTool,
    "cewl": CewlTool,
    
    # 后渗透
    "linpeas": LinpeasTool,
    "winpeas": WinpeasTool,
    "linenum": LinenumTool,
    "linux-exploit-suggester": LinuxExploitSuggesterTool,
    
    # 其他
    "curl": CurlTool,
    "wget": WgetTool,
    "nc": NcTool,
    "socat": SocatTool,
}


def get_tool(tool_name: str) -> Optional[KaliTool]:
    """获取工具实例"""
    if tool_name in TOOL_REGISTRY:
        return TOOL_REGISTRY[tool_name]()
    return None


def get_all_tools() -> List[str]:
    """获取所有可用工具名称"""
    return list(TOOL_REGISTRY.keys())


async def execute_tool(tool_name: str, callback: Optional[Callable] = None, **kwargs) -> Optional[ToolResult]:
    """便捷函数：执行工具"""
    tool = get_tool(tool_name)
    if tool:
        return await tool.execute(callback=callback, **kwargs)
    return None
