"""
SkidCon 动态攻击链引擎
根据扫描到的服务动态选择工具，实现智能攻击策略
"""

from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class ServiceInfo:
    """服务信息"""
    port: str
    protocol: str
    service: str
    version: str = ""
    product: str = ""
    state: str = "open"


class AttackChainEngine:
    """根据发现的服务动态选择工具的攻击链引擎"""
    
    # 服务到工具的映射表
    SERVICE_TOOL_MAP = {
        "http": [
            {"tool": "nikto", "params": {"url": "{url}"}},
            {"tool": "sqlmap", "params": {"url": "{url}"}},
            {"tool": "gobuster", "params": {"url": "{url}", "wordlist": "{wordlist}"}},
            {"tool": "nuclei", "params": {"url": "{url}"}},
            {"tool": "whatweb", "params": {"url": "{url}"}},
        ],
        "https": [
            {"tool": "nikto", "params": {"url": "{url}"}},
            {"tool": "sqlmap", "params": {"url": "{url}"}},
            {"tool": "gobuster", "params": {"url": "{url}", "wordlist": "{wordlist}"}},
            {"tool": "nuclei", "params": {"url": "{url}"}},
            {"tool": "whatweb", "params": {"url": "{url}"}},
        ],
        "ssh": [
            {"tool": "hydra", "params": {"target": "{host}", "service": "ssh", "port": "{port}"}},
            {"tool": "nmap-ssh-audit", "params": {"target": "{host}", "port": "{port}"}},
        ],
        "smb": [
            {"tool": "enum4linux", "params": {"target": "{host}"}},
            {"tool": "smbclient", "params": {"target": "{host}"}},
            {"tool": "crackmapexec", "params": {"target": "{host}", "service": "smb"}},
        ],
        "microsoft-ds": [
            {"tool": "enum4linux", "params": {"target": "{host}"}},
            {"tool": "smbclient", "params": {"target": "{host}"}},
            {"tool": "crackmapexec", "params": {"target": "{host}", "service": "smb"}},
        ],
        "netbios-ssn": [
            {"tool": "enum4linux", "params": {"target": "{host}"}},
            {"tool": "smbclient", "params": {"target": "{host}"}},
        ],
        "ftp": [
            {"tool": "hydra", "params": {"target": "{host}", "service": "ftp", "port": "{port}"}},
            {"tool": "nmap-ftp-enum", "params": {"target": "{host}", "port": "{port}"}},
        ],
        "mysql": [
            {"tool": "hydra", "params": {"target": "{host}", "service": "mysql", "port": "{port}"}},
            {"tool": "nmap-mysql-enum", "params": {"target": "{host}", "port": "{port}"}},
            {"tool": "sqlmap", "params": {"url": "mysql://{host}:{port}"}},
        ],
        "postgresql": [
            {"tool": "hydra", "params": {"target": "{host}", "service": "postgresql", "port": "{port}"}},
            {"tool": "nmap-pgsql-enum", "params": {"target": "{host}", "port": "{port}"}},
        ],
        "smtp": [
            {"tool": "nmap-smtp-enum", "params": {"target": "{host}", "port": "{port}"}},
            {"tool": "hydra", "params": {"target": "{host}", "service": "smtp", "port": "{port}"}},
        ],
        "dns": [
            {"tool": "dnsrecon", "params": {"domain": "{host}"}},
            {"tool": "dnsenum", "params": {"domain": "{host}"}},
            {"tool": "subfinder", "params": {"domain": "{host}"}},
        ],
        "domain": [
            {"tool": "dnsrecon", "params": {"domain": "{host}"}},
            {"tool": "dnsenum", "params": {"domain": "{host}"}},
            {"tool": "subfinder", "params": {"domain": "{host}"}},
        ],
        "snmp": [
            {"tool": "snmpwalk", "params": {"target": "{host}", "port": "{port}"}},
            {"tool": "onesixtyone", "params": {"target": "{host}"}},
        ],
        "rdp": [
            {"tool": "hydra", "params": {"target": "{host}", "service": "rdp", "port": "{port}"}},
            {"tool": "nmap-rdp-enum", "params": {"target": "{host}", "port": "{port}"}},
        ],
        "ms-wbt-server": [
            {"tool": "hydra", "params": {"target": "{host}", "service": "rdp", "port": "{port}"}},
            {"tool": "nmap-rdp-enum", "params": {"target": "{host}", "port": "{port}"}},
        ],
        "mongodb": [
            {"tool": "nmap-mongodb-enum", "params": {"target": "{host}", "port": "{port}"}},
        ],
        "redis": [
            {"tool": "redis-cli", "params": {"target": "{host}", "port": "{port}"}},
        ],
        "ldap": [
            {"tool": "nmap-ldap-enum", "params": {"target": "{host}", "port": "{port}"}},
        ],
        "kerberos": [
            {"tool": "nmap-kerberos-enum", "params": {"target": "{host}", "port": "{port}"}},
        ],
        "telnet": [
            {"tool": "hydra", "params": {"target": "{host}", "service": "telnet", "port": "{port}"}},
        ],
        "vnc": [
            {"tool": "hydra", "params": {"target": "{host}", "service": "vnc", "port": "{port}"}},
            {"tool": "nmap-vnc-enum", "params": {"target": "{host}", "port": "{port}"}},
        ],
        "winrm": [
            {"tool": "crackmapexec", "params": {"target": "{host}", "service": "winrm"}},
            {"tool": "evil-winrm", "params": {"target": "{host}", "port": "{port}"}},
        ],
    }
    
    # 通用工具（无论什么服务都执行）
    GENERAL_TOOLS = [
        {"tool": "nmap", "params": {"target": "{target}", "port": "{port}"}},
        {"tool": "subfinder", "params": {"domain": "{target}"}},
        {"tool": "whois", "params": {"domain": "{target}"}},
        {"tool": "dig", "params": {"domain": "{target}"}},
    ]
    
    def __init__(self):
        self.discovered_services: List[ServiceInfo] = []
        self.executed_tools: set = set()
    
    def parse_nmap_results(self, recon_results: Dict) -> List[ServiceInfo]:
        """从 Nmap 结果中解析服务信息"""
        services = []
        
        # 尝试从结构化数据中解析
        nmap_data = recon_results.get("nmap", {})
        parsed_data = nmap_data.get("parsed_data", {})
        
        # 如果 nmap 工具实现了结构化解析
        if "ports" in parsed_data:
            for port_info in parsed_data["ports"]:
                if port_info.get("state") == "open":
                    services.append(ServiceInfo(
                        port=port_info.get("port", ""),
                        protocol=port_info.get("protocol", "tcp"),
                        service=port_info.get("service", "unknown"),
                        version=port_info.get("version", ""),
                        product=port_info.get("product", ""),
                    ))
            return services
        
        # 回退：从原始输出中解析
        raw_output = nmap_data.get("raw_output", "")
        if raw_output:
            services = self._parse_nmap_raw_output(raw_output)
        
        return services
    
    def _parse_nmap_raw_output(self, raw_output: str) -> List[ServiceInfo]:
        """从 Nmap 原始输出中解析服务信息"""
        import re
        services = []
        
        # 匹配开放端口行
        port_pattern = r'^(\d+/\w+)\s+(open)\s+(\S+)\s+(.*)$'
        current_ip = None
        
        for line in raw_output.split('\n'):
            # 匹配 IP 地址
            ip_match = re.match(r'^Nmap scan report for\s+(\S+)', line)
            if ip_match:
                current_ip = ip_match.group(1)
            
            # 匹配端口
            port_match = re.match(port_pattern, line)
            if port_match:
                port = port_match.group(1)
                state = port_match.group(2)
                service = port_match.group(3)
                version = port_match.group(4)
                
                if state == "open":
                    services.append(ServiceInfo(
                        port=port,
                        protocol=port.split('/')[1] if '/' in port else "tcp",
                        service=service,
                        version=version,
                    ))
        
        return services
    
    def select_tools_for_recon(self, target: str, port: Optional[str] = None) -> List[Tuple[str, Dict]]:
        """选择信息收集阶段的工具"""
        tools = []
        
        for tool_config in self.GENERAL_TOOLS:
            tool_name = tool_config["tool"]
            params = self._build_params(tool_config["params"], target=target, port=port)
            tools.append((tool_name, params))
        
        return tools
    
    def select_tools_for_services(self, target: str, services: List[ServiceInfo], 
                                   wordlist: str = "wordlists/directories.txt") -> List[Tuple[str, Dict]]:
        """根据发现的服务选择工具"""
        tools = []
        self.executed_tools.clear()
        
        for service in services:
            service_name = service.service.lower()
            
            if service_name in self.SERVICE_TOOL_MAP:
                for tool_config in self.SERVICE_TOOL_MAP[service_name]:
                    tool_name = tool_config["tool"]
                    
                    # 避免重复执行同一工具
                    tool_key = f"{tool_name}_{service.port}"
                    if tool_key in self.executed_tools:
                        continue
                    
                    self.executed_tools.add(tool_key)
                    
                    # 构建参数
                    params = self._build_params(
                        tool_config["params"],
                        target=target,
                        host=target,
                        port=service.port.split('/')[0] if '/' in service.port else service.port,
                        url=f"http{'s' if service.service in ['https', 'ssl/http'] else ''}://{target}:{service.port.split('/')[0] if '/' in service.port else service.port}",
                        wordlist=wordlist,
                        service=service_name,
                    )
                    
                    tools.append((tool_name, params))
        
        return tools
    
    def select_tools_for_vulnerability(self, target: str, services: List[ServiceInfo]) -> List[Tuple[str, Dict]]:
        """选择漏洞检测阶段的工具"""
        tools = []
        
        # 对所有 HTTP/HTTPS 服务执行 Web 漏洞扫描
        for service in services:
            if service.service.lower() in ["http", "https", "ssl/http"]:
                port = service.port.split('/')[0] if '/' in service.port else service.port
                url = f"http{'s' if service.service in ['https', 'ssl/http'] else ''}://{target}:{port}"
                
                tools.append(("nuclei", {"url": url}))
                tools.append(("sqlmap", {"url": url}))
                tools.append(("searchsploit", {"query": f"{service.product} {service.version}" if service.product else target}))
        
        # 如果没有发现特定服务，执行通用扫描
        if not tools:
            tools.append(("nuclei", {"url": f"http://{target}"}))
            tools.append(("searchsploit", {"query": target}))
        
        return tools
    
    def _build_params(self, param_template: Dict, **kwargs) -> Dict:
        """构建工具参数，安全地替换模板变量"""
        params = {}
        for key, value in param_template.items():
            if isinstance(value, str):
                # 安全地替换 {variable} 模板
                try:
                    params[key] = value.format(**kwargs)
                except KeyError:
                    # 如果模板变量不存在，保留原值
                    params[key] = value
            else:
                params[key] = value
        return params
    
    def get_attack_summary(self, services: List[ServiceInfo]) -> Dict:
        """生成攻击摘要"""
        summary = {
            "total_services": len(services),
            "service_types": {},
            "recommended_tools": [],
        }
        
        for service in services:
            service_name = service.service.lower()
            if service_name not in summary["service_types"]:
                summary["service_types"][service_name] = []
            summary["service_types"][service_name].append(service.port)
            
            if service_name in self.SERVICE_TOOL_MAP:
                for tool_config in self.SERVICE_TOOL_MAP[service_name]:
                    tool_name = tool_config["tool"]
                    if tool_name not in summary["recommended_tools"]:
                        summary["recommended_tools"].append(tool_name)
        
        return summary
