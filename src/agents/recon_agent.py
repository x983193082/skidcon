"""
Recon Agent - 信息收集Agent
负责目标侦察、端口扫描、服务识别等
"""
import asyncio
import socket
import os
from typing import Dict, Any, List, Optional
from datetime import datetime
from loguru import logger
from ..core.agent_interface import BaseAgent, AgentRole, AgentState
from ..tools.nmap_wrapper import NmapWrapper
class ReconAgent(BaseAgent):
    """
    信息收集Agent

    职责：
    - 端口扫描
    - 服务版本检测
    - 子域名枚举
    - Web技术栈识别
    """
    # 类常量：常见的Web端口
    WEB_PORTS = {80, 443, 8080, 8443}
    def __init__(
        self,
        name: str = "ReconAgent",
        description: str = "负责目标信息收集和侦察",
        config: Dict[str, Any] = None
    ):
        super().__init__(
            name=name,
            role=AgentRole.RECON,
            description=description,
            config=config
        )
        # 初始化扫描工具
        self.nmap = NmapWrapper()
        self.masscan = None  # 未来添加: MasscanWrapper()
        self.add_tool(self.nmap)
    async def execute(self, target: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        执行信息收集 - 主流程

        执行顺序：
        1. 端口扫描（必须先执行，后续依赖端口列表）
        2. 并发执行：服务检测 + 子域名枚举 + 技术识别
        """
        self.update_state(AgentState.RUNNING)
        context = context or {}
        # 初始化结果字典
        result = {
            "target": target,
            "scan_time": datetime.now().isoformat(),
            "hosts": [],
            "ports": [],
            "services": [],
            "subdomains": [],
            "technologies": [],
            "vulnerabilities": []
        }
        try:
            # 步骤1：端口扫描
            logger.info(f"Step 1: Port scan on {target}")
            result = await self._run_port_scan(target, result)
            # 步骤2：并发执行三个任务
            # 注意：这三个任务之间没有依赖关系，可以并发执行提升性能
            logger.info("Step 2: 并发执行服务检测、子域名枚举、技术识别")
            service_task = self._detect_service_versions(target, result)
            subdomain_task = self._enumerate_subdomains(target)
            tech_task = self._detect_technologies(target, result["ports"])
            # asyncio.gather 并发等待所有任务完成
            updated_result, subdomains, technologies = await asyncio.gather(
                service_task,
                subdomain_task,
                tech_task
            )
            # 合并结果
            result = updated_result
            result["subdomains"] = subdomains
            result["technologies"] = technologies
            # 保存上下文，供其他Agent使用
            self.set_context(result)
            self.update_state(AgentState.COMPLETED)
            return result
        except Exception as e:
            self.update_state(AgentState.FAILED)
            logger.exception(f"Reconnaissance failed: {e}")
            return {
                "target": target,
                "error": str(e),
                "success": False
            }
    async def _run_port_scan(self, target: str, result: Dict) -> Dict:
        """
        遍历所有扫描工具执行端口扫描

        设计思路：
        - 遍历 self.tools 列表中的所有工具
        - 检查工具是否有 quick_scan 方法
        - 收集所有工具的扫描结果
        """
        all_hosts = []
        all_ports = []
        for tool in self.tools:
            # 检查工具是否有 quick_scan 方法（动态调用）
            if not hasattr(tool, 'quick_scan'):
                continue
            try:
                scan_result = await tool.quick_scan(target)
                # 防御性检查：确保返回数据有效
                if not (scan_result.success and scan_result.data):
                    logger.debug(f"Tool {tool.name} returned invalid data")
                    continue
                # 遍历扫描结果
                for host in scan_result.data.get("hosts", []):
                    all_hosts.append({
                        "address": host.get("address"),
                        "status": "up" if host.get("ports") else "down",
                        "scanner": tool.name  # 记录是哪个工具扫描到的
                    })
                    for port in host.get("ports", []):
                        if port.get("state") == "open":
                            all_ports.append({
                                "port": port.get("port"),
                                "protocol": port.get("protocol"),
                                "service": port.get("service"),
                                "state": "open",
                                "scanner": tool.name
                            })
            except Exception as e:
                logger.exception(f"Tool {tool.name} port scan failed")
        result["hosts"] = all_hosts
        result["ports"] = all_ports
        return result
    async def _detect_service_versions(self, target: str, result: Dict) -> Dict:
        """
        遍历所有工具检测服务版本

        检测逻辑：
        - 只检测 WEB_PORTS 中的端口（80, 443, 8080, 8443）
        - 以及特权端口（< 1024）
        """
        services = []
        for tool in self.tools:
            if not hasattr(tool, 'service_scan'):
                continue
            try:
                service_result = await tool.service_scan(target)
                if not (service_result.success and service_result.data):
                    logger.debug(f"Tool {tool.name} service scan failed")
                    continue
                for host in service_result.data.get("hosts", []):
                    for svc in host.get("ports", []):
                        if svc.get("state") == "open":
                            port = svc.get("port")
                            # 只检测Web端口和特权端口
                            if port in self.WEB_PORTS or (isinstance(port, int) and port < 1024):
                                services.append({
                                    "port": port,
                                    "service": svc.get("service"),
                                    "version": "detected",
                                    "scanner": tool.name
                                })
            except Exception as e:
                logger.exception(f"Tool {tool.name} service scan failed")
        result["services"] = services
        return result
    async def _enumerate_subdomains(self, target: str) -> List[Dict[str, str]]:
        """
        异步枚举子域名

        实现思路：
        1. 先检测是否存在泛解析（Wildcard DNS）
           - 随机生成一个不可能存在的子域名
           - 如果能解析出IP，说明存在泛解析
        2. 并发解析所有常见子域名前缀
           - 使用 getaddrinfo 替代 gethostbyname（推荐）
           - 过滤掉泛解析的IP
        """
        common_prefixes = [
            "www", "mail", "ftp", "localhost", "webmail", "smtp",
            "pop", "ns1", "webdisk", "ns2", "cpanel", "whm",
            "autodiscover", "autoconfig", "m", "imap", "test",
            "ns", "blog", "pop3", "dev", "www2", "admin",
            "forum", "news", "vpn", "ns3", "mail2", "new",
            "mysql", "old", "lists", "support", "mobile", "mx",
            "static", "docs", "beta", "shop", "sql", "secure"
        ]

        loop = asyncio.get_event_loop()
        # ==== 步骤1: 检测泛解析 ====
        # 随机生成一个子域名，检测是否有泛解析
        random_sub = f"no-such-subdomain-{os.urandom(4).hex()}.{target}"
        wildcard_ip = None
        try:
            wildcard_ip = await loop.run_in_executor(None, socket.gethostbyname, random_sub)
            if wildcard_ip:
                logger.info(f"检测到泛解析: {target} -> {wildcard_ip}")
        except socket.gaierror:
            wildcard_ip = None  # 无泛解析
        # ==== 步骤2: 定义解析函数 ====
        async def resolve(prefix: str) -> Optional[Dict[str, str]]:
            subdomain = f"{prefix}.{target}"
            try:
                def _resolve():
                    try:
                        # getaddrinfo 返回 [(family, type, proto, canonname, sockaddr)]
                        result = socket.getaddrinfo(subdomain, None)
                        return result[0][4][0] if result else None
                    except socket.gaierror:
                        return None
                ip = await loop.run_in_executor(None, _resolve)
                if ip is None:
                    return None
                # 过滤泛解析结果
                if wildcard_ip and ip == wildcard_ip:
                    logger.debug(f"过滤泛解析子域名: {subdomain}")
                    return None
                return {"subdomain": subdomain, "ip": ip}
            except Exception:
                return None
        # ==== 步骤3: 并发解析 ====
        tasks = [resolve(prefix) for prefix in common_prefixes]
        results = await asyncio.gather(*tasks)

        # 过滤掉 None 值
        subdomains = [res for res in results if res is not None]
        return subdomains

    async def _detect_technologies(self, target: str, ports: List[Dict]) -> List[str]:
        """
        异步识别 Web 技术栈

        实现思路：
        1. 筛选出开放的 Web 端口
        2. 并发测试每个端口的连通性
        3. 根据端口返回对应的技术标签
        """
        technologies = []
        open_web_ports = [
            p["port"] for p in ports
            if isinstance(p, dict) and p.get("port") in self.WEB_PORTS
        ]
        if not open_web_ports:
            return technologies
        loop = asyncio.get_event_loop()
        async def test_port(port: int) -> Optional[str]:
            """测试端口并返回技术标签"""
            def _test():
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(3)
                    result = sock.connect_ex((target, port))
                    sock.close()
                    return result == 0
                except Exception:
                    return False
            is_open = await loop.run_in_executor(None, _test)
            if is_open:
                if port == 80:
                    return "HTTP"
                elif port == 443:
                    return "HTTPS"
                elif port == 8080:
                    return "HTTP-Proxy"
                elif port == 8443:
                    return "HTTPS-Alt"
            return None
        # 并发测试所有端口
        tasks = [test_port(port) for port in open_web_ports]
        results = await asyncio.gather(*tasks)
        for tech in results:
            if tech:
                technologies.append(tech)
        return technologies
    def validate_result(self, result: Dict[str, Any]) -> bool:
        """验证收集结果是否有效"""
        if not result:
            return False
        if "error" in result:
            return False
        if "target" not in result:
            return False
        return True
    def report(self) -> Dict[str, Any]:
        """生成信息收集报告"""
        return {
            "agent": self.name,
            "role": self.role.value,
            "state": self.state.value,
            "description": self.description,
            "last_result": self._context
        }