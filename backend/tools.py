"""
SkidCon Kali 工具封装模块
封装 50+ 渗透测试工具，提供统一的异步执行接口
"""

import asyncio
import json
import re
import shutil
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
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
    execution_time: float = 0.0
    retry_count: int = 0


class KaliTool:
    """Kali 工具基类"""
    
    def __init__(self, tool_name: str, command_template: str, timeout: int = TASK_TIMEOUT):
        self.tool_name = tool_name
        self.command_template = command_template
        self.timeout = timeout
        self.max_retries = 2
    
    def build_command(self, **kwargs) -> str:
        """构建命令"""
        return self.command_template.format(**kwargs)
    
    async def execute(self, callback: Optional[Callable] = None, **kwargs) -> ToolResult:
        """异步执行工具（带重试机制）"""
        import time
        
        # 首次执行前检查工具是否可用，避免无效重试
        if not check_tool_available(self.tool_name):
            if callback:
                await callback(f"[{self.tool_name}] 工具未安装，跳过执行")
            return ToolResult(
                tool_name=self.tool_name,
                command="",
                stdout="",
                stderr=f"工具 {self.tool_name} 未安装",
                returncode=-1,
                success=False,
                execution_time=0.0,
                retry_count=0
            )
        
        for attempt in range(self.max_retries + 1):
            start_time = time.time()
            command = self.build_command(**kwargs)
            
            if callback:
                retry_info = f" (重试 {attempt}/{self.max_retries})" if attempt > 0 else ""
                await callback(f"[{self.tool_name}] 执行命令{retry_info}: {command}")
            
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
                        decoded = line.decode('utf-8', errors='ignore').rstrip()
                        # 过滤空行和纯进度信息
                        if not decoded.strip():
                            continue
                        data_list.append(decoded + '\n')
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
                execution_time = time.time() - start_time
                
                stdout = ''.join(stdout_data)
                stderr = ''.join(stderr_data)
                
                result = ToolResult(
                    tool_name=self.tool_name,
                    command=command,
                    stdout=stdout,
                    stderr=stderr,
                    returncode=returncode,
                    success=returncode == 0,
                    execution_time=execution_time,
                    retry_count=attempt
                )
                
                # 解析输出
                result.parsed_data = self.parse_output(stdout, stderr)
                
                # 如果成功或已达到最大重试次数，返回结果
                if result.success or attempt >= self.max_retries:
                    return result
                
                # 否则等待后重试
                if callback:
                    await callback(f"[{self.tool_name}] 执行失败，准备重试 ({attempt + 1}/{self.max_retries})")
                await asyncio.sleep(2 ** attempt)  # 指数退避
                
            except asyncio.TimeoutError:
                execution_time = time.time() - start_time
                try:
                    process.kill()
                except:
                    pass
                if callback:
                    await callback(f"[{self.tool_name}] 执行超时")
                
                if attempt >= self.max_retries:
                    return ToolResult(
                        tool_name=self.tool_name,
                        command=command,
                        stdout="",
                        stderr="执行超时",
                        returncode=-1,
                        success=False,
                        execution_time=execution_time,
                        retry_count=attempt
                    )
                await asyncio.sleep(2 ** attempt)
                
            except Exception as e:
                execution_time = time.time() - start_time
                if callback:
                    await callback(f"[{self.tool_name}] 执行错误: {str(e)}")
                
                if attempt >= self.max_retries:
                    return ToolResult(
                        tool_name=self.tool_name,
                        command=command,
                        stdout="",
                        stderr=str(e),
                        returncode=-1,
                        success=False,
                        execution_time=execution_time,
                        retry_count=attempt
                    )
                await asyncio.sleep(2 ** attempt)
        
        # 不应该到达这里
        return ToolResult(
            tool_name=self.tool_name,
            command=command,
            stdout="",
            stderr="未知错误",
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
        super().__init__("nmap", "nmap -sV -sC -O -oX - {target}")
    
    def build_command(self, **kwargs) -> str:
        """构建命令，支持端口参数"""
        target = kwargs.get("target", "")
        port = kwargs.get("port")
        if port:
            return f"nmap -sV -sC -O -oX - -p {port} {target}"
        return f"nmap -sV -sC -O -oX - {target}"
    
    def parse_output(self, stdout, stderr):
        """解析 Nmap XML 输出"""
        import xml.etree.ElementTree as ET
        
        # 从混杂输出中提取 XML 内容
        xml_content = self._extract_xml(stdout)
        if not xml_content:
            # 回退到文本解析
            return self._parse_text_output(stdout)
        
        try:
            root = ET.fromstring(xml_content)
            ports = []
            for host in root.findall('.//host'):
                ip = host.find('address').get('addr') if host.find('address') is not None else "unknown"
                for port_elem in host.findall('.//port'):
                    port_id = port_elem.get('portid')
                    protocol = port_elem.get('protocol')
                    state_elem = port_elem.find('state')
                    state = state_elem.get('state') if state_elem is not None else "unknown"
                    service = port_elem.find('service')
                    ports.append({
                        "ip": ip,
                        "port": f"{port_id}/{protocol}",
                        "state": state,
                        "service": service.get('name') if service is not None else "unknown",
                        "version": service.get('version', '') if service is not None else "",
                        "product": service.get('product', '') if service is not None else "",
                    })
            return {
                "ports": ports, 
                "hosts": len(root.findall('.//host')),
                "raw_output": xml_content[:2000]
            }
        except ET.ParseError:
            # 回退到文本解析
            return self._parse_text_output(stdout)
    
    def _extract_xml(self, stdout: str) -> Optional[str]:
        """从 nmap 输出中提取 XML 内容（过滤进度信息等干扰）"""
        # 查找 <?xml 或 <nmaprun 开始位置
        xml_start = stdout.find('<?xml')
        if xml_start == -1:
            xml_start = stdout.find('<nmaprun')
        
        if xml_start == -1:
            return None
        
        # 从 XML 开始位置截取
        xml_content = stdout[xml_start:]
        
        # 尝试找到匹配的根元素闭合
        # 简单策略：找到最后一个 </nmaprun> 并截取到那里
        xml_end = xml_content.rfind('</nmaprun>')
        if xml_end != -1:
            xml_content = xml_content[:xml_end + len('</nmaprun>')]
        
        return xml_content if xml_content.strip() else None
    
    def _parse_text_output(self, stdout):
        """从文本输出中解析端口信息"""
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
        from config import WORDLISTS_DIR
        default_wordlist = str(WORDLISTS_DIR / "directories.txt")
        super().__init__("gobuster", f"gobuster dir -u {{url}} -w {default_wordlist} -t 20 --no-error")
    
    def build_command(self, **kwargs) -> str:
        """构建命令，支持自定义字典"""
        url = kwargs.get("url", "")
        wordlist = kwargs.get("wordlist")
        if wordlist:
            return f"gobuster dir -u {url} -w {wordlist} -t 20 --no-error"
        from config import WORDLISTS_DIR
        default_wordlist = str(WORDLISTS_DIR / "directories.txt")
        return f"gobuster dir -u {url} -w {default_wordlist} -t 20 --no-error"
    
    def parse_output(self, stdout, stderr):
        dirs = []
        for line in stdout.split('\n'):
            if line.startswith("Found:") or (line.startswith("/") and "Status:" in line):
                dirs.append(line.strip())
        return {"directories": dirs, "count": len(dirs), "raw_output": stdout[:2000]}


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
        super().__init__("nuclei", "nuclei -u {url} -json -silent {templates}")
    
    def build_command(self, **kwargs) -> str:
        """构建命令，支持模板参数"""
        url = kwargs.get("url", "")
        templates = kwargs.get("templates", "")
        if templates:
            return f"nuclei -u {url} -json -silent -t {templates}"
        return f"nuclei -u {url} -json -silent"
    
    def parse_output(self, stdout, stderr):
        """解析 Nuclei JSON 输出"""
        vulns = []
        for line in stdout.strip().split('\n'):
            if line.strip():
                try:
                    vuln = json.loads(line)
                    vulns.append({
                        "template": vuln.get("template-id", ""),
                        "name": vuln.get("info", {}).get("name", ""),
                        "severity": vuln.get("info", {}).get("severity", ""),
                        "url": vuln.get("matched-at", ""),
                        "cve": vuln.get("info", {}).get("classification", {}).get("cve-id", []),
                        "description": vuln.get("info", {}).get("description", ""),
                        "reference": vuln.get("info", {}).get("reference", []),
                    })
                except json.JSONDecodeError:
                    continue
        return {"vulnerabilities": vulns, "count": len(vulns), "raw_output": stdout[:2000]}


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
    
    def build_command(self, **kwargs) -> str:
        """构建命令，提供默认用户名和字典路径"""
        target = kwargs.get("target", "")
        service = kwargs.get("service", "ssh")
        user = kwargs.get("user", "admin")
        port = kwargs.get("port")
        
        from config import WORDLISTS_DIR
        wordlist = kwargs.get("wordlist", str(WORDLISTS_DIR / "passwords.txt"))
        
        if port:
            return f"hydra -l {user} -P {wordlist} -s {port} {target} {service}"
        return f"hydra -l {user} -P {wordlist} {target} {service}"
    
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


class ExecuteKaliToolWrapper(KaliTool):
    """通用 Kali 工具执行器包装 - 通过 execute_kali_tool 调用任何工具"""
    def __init__(self):
        super().__init__("execute_kali_tool", "{tool} {args}")
    
    def build_command(self, **kwargs) -> str:
        """构建命令"""
        tool = kwargs.get("tool", "")
        args = kwargs.get("args", "")
        if not tool:
            return "echo '错误: 未指定工具名称'"
        return f"{tool} {args}"
    
    async def execute(self, callback: Optional[Callable] = None, **kwargs) -> ToolResult:
        """执行通用工具调用"""
        import time
        
        tool = kwargs.get("tool", "")
        args = kwargs.get("args", "")
        
        if not tool:
            return ToolResult(
                tool_name="execute_kali_tool",
                command="",
                stdout="",
                stderr="错误: 未指定工具名称",
                returncode=-1,
                success=False
            )
        
        # 安全检查
        if not check_tool_available(tool):
            if callback:
                await callback(f"[execute_kali_tool] 工具 '{tool}' 未安装，跳过执行")
            return ToolResult(
                tool_name="execute_kali_tool",
                command=f"{tool} {args}",
                stdout="",
                stderr=f"工具 '{tool}' 未安装或不在 PATH 中",
                returncode=-1,
                success=False
            )
        
        command = f"{tool} {args}"
        start_time = time.time()
        
        if callback:
            await callback(f"[execute_kali_tool] 执行: {command}")
        
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
                    decoded = line.decode('utf-8', errors='ignore').rstrip()
                    if not decoded.strip():
                        continue
                    data_list.append(decoded + '\n')
                    if callback:
                        await callback(f"[{tool}] {prefix}: {decoded.strip()}")
            
            await asyncio.wait_for(
                asyncio.gather(
                    read_stream(process.stdout, stdout_data, "OUT"),
                    read_stream(process.stderr, stderr_data, "ERR")
                ),
                timeout=TASK_TIMEOUT
            )
            
            returncode = await process.wait()
            execution_time = time.time() - start_time
            
            stdout = ''.join(stdout_data)
            stderr = ''.join(stderr_data)
            
            return ToolResult(
                tool_name=f"execute_kali_tool({tool})",
                command=command,
                stdout=stdout,
                stderr=stderr,
                returncode=returncode,
                success=returncode == 0,
                execution_time=execution_time
            )
            
        except asyncio.TimeoutError:
            return ToolResult(
                tool_name=f"execute_kali_tool({tool})",
                command=command,
                stdout="",
                stderr="执行超时",
                returncode=-1,
                success=False,
                execution_time=time.time() - start_time
            )
        except Exception as e:
            return ToolResult(
                tool_name=f"execute_kali_tool({tool})",
                command=command,
                stdout="",
                stderr=str(e),
                returncode=-1,
                success=False,
                execution_time=time.time() - start_time
            )


def get_tool(tool_name: str) -> Optional[KaliTool]:
    """获取工具实例"""
    if tool_name == "execute_kali_tool":
        return ExecuteKaliToolWrapper()
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


# ==================== 工具可用性检查 ====================

def check_tool_available(tool_name: str) -> bool:
    """检查工具是否在系统中可用"""
    return shutil.which(tool_name) is not None


async def validate_tools() -> Dict[str, bool]:
    """验证所有工具可用性"""
    results = {}
    for tool_name in get_all_tools():
        results[tool_name] = check_tool_available(tool_name)
    return results


def get_available_tools() -> List[str]:
    """获取当前系统中可用的工具列表"""
    return [name for name in get_all_tools() if check_tool_available(name)]


def get_unavailable_tools() -> List[str]:
    """获取当前系统中不可用的工具列表"""
    return [name for name in get_all_tools() if not check_tool_available(name)]
