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
    - 端口扫描（支持多种扫描类型）
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
        self.masscan = None
        self.add_tool(self.nmap)

        # 从config读取扫描配置，默认为 ["quick"]
        # 支持: quick, full, vuln
        scan_profiles = config.get("scan_profiles", ["quick"]) if config else ["quick"]
        # 过滤掉无效的扫描类型
        valid_scans = {"quick", "full", "vuln"}
        self.supported_scans = [s for s in scan_profiles if s in valid_scans]
        if not self.supported_scans:
            self.supported_scans = ["quick"]

    async def execute(self, target: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """执行信息收集 - 支持多种扫描类型"""
        self.update_state(AgentState.RUNNING)
        context = context or {}
        result = {
            "target": target,
            "scan_time": datetime.now().isoformat(),
            "hosts": [],
            "ports": [],
            "services": [],
            "subdomains": [],
            "technologies": [],
            "vulnerabilities": [],
            "scan_profiles_used": self.supported_scans  # 记录使用的扫描配置
        }
        try:
            # 步骤1：根据配置的扫描类型执行扫描
            logger.info(f"Step 1: Port scan with profiles: {self.supported_scans}")

            for scan_type in self.supported_scans:
                logger.info(f"Running {scan_type} scan...")
                result = await self._run_scan(target, result, scan_type)

                if result.get("ports") and scan_type != self.supported_scans[-1]:
                    logger.info(f"Found {len(result['ports'])} ports, continuing...")
            # 步骤2：并发执行服务检测、子域名枚举、技术识别
            logger.info("Step 2: 并发执行服务检测、子域名枚举、技术识别")
            service_task = self._detect_services(target, result)
            subdomain_task = self._enumerate_subdomains(target)
            tech_task = self._detect_technologies(target, result["ports"])
            updated_result, subdomains, technologies = await asyncio.gather(
                service_task,
                subdomain_task,
                tech_task
            )
            result = updated_result
            result["subdomains"] = subdomains
            result["technologies"] = technologies
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
    async def _run_scan(self, target: str, result: Dict, scan_type: str = "quick") -> Dict:
        """
        通用扫描方法 - 遍历所有工具执行指定类型的扫描

        Args:
            target: 目标地址
            result: 结果字典
            scan_type: 扫描类型 (quick/full/vuln/stealth)

        Example:
            await self._run_scan(target, result, "quick")    # 快速扫描
            await self._run_scan(target, result, "full")     # 全端口扫描
            await self._run_scan(target, result, "vuln")     # 漏洞扫描
        """
        all_hosts = []
        all_ports = []

        # 根据 scan_type 构建方法名
        method_name = f"{scan_type}_scan"
        for tool in self.tools:
            # 优先尝试调用对应的扫描方法
            if hasattr(tool, method_name):
                try:
                    scan_result = await getattr(tool, method_name)(target)

                    # 防御性检查：确保返回数据有效
                    if not (scan_result.success and scan_result.data):
                        logger.debug(f"Tool {tool.name} {scan_type} scan returned invalid data")
                        continue

                    # 处理扫描结果
                    for host in scan_result.data.get("hosts", []):
                        all_hosts.append({
                            "address": host.get("address"),
                            "status": "up" if host.get("ports") else "down",
                            "scanner": tool.name,
                            "scan_type": scan_type
                        })

                        for port in host.get("ports", []):
                            if port.get("state") == "open":
                                all_ports.append({
                                    "port": port.get("port"),
                                    "protocol": port.get("protocol"),
                                    "service": port.get("service"),
                                    "state": "open",
                                    "scanner": tool.name,
                                    "scan_type": scan_type
                                })
                except Exception as e:
                    logger.exception(f"Tool {tool.name} {scan_type} scan failed")

            # 如果工具没有对应的扫描方法，尝试通用 execute 方法
            elif hasattr(tool, 'execute'):
                try:
                    # 尝试使用 profile 参数调用通用 execute
                    scan_result = await tool.execute(target, {"profile": scan_type})

                    if not (scan_result.success and scan_result.data):
                        logger.debug(f"Tool {tool.name} execute with profile {scan_type} failed")
                        continue

                    # 处理结果（同上）
                    for host in scan_result.data.get("hosts", []):
                        all_hosts.append({
                            "address": host.get("address"),
                            "status": "up" if host.get("ports") else "down",
                            "scanner": tool.name,
                            "scan_type": scan_type
                        })

                        for port in host.get("ports", []):
                            if port.get("state") == "open":
                                all_ports.append({
                                    "port": port.get("port"),
                                    "protocol": port.get("protocol"),
                                    "service": port.get("service"),
                                    "state": "open",
                                    "scanner": tool.name,
                                    "scan_type": scan_type
                                })
                except Exception as e:
                    logger.exception(f"Tool {tool.name} execute failed")
        result["hosts"] = all_hosts
        result["ports"] = all_ports
        return result
    async def _detect_services(self, target: str, result: Dict) -> Dict:
        """
        通用服务检测 - 遍历所有工具检测服务版本

        尝试调用工具的以下方法（按优先级）：
        1. service_scan - 专用服务扫描
        2. version_scan - 版本检测
        3. execute - 通用执行（带service参数）
        """
        services = []

        # 尝试的方法名列表（按优先级）
        method_names = ["service_scan", "version_scan"]
        for tool in self.tools:
            method_found = False

            # 尝试工具支持的检测方法
            for method_name in method_names:
                if hasattr(tool, method_name):
                    method_found = True
                    try:
                        service_result = await getattr(tool, method_name)(target)
                        if not (service_result.success and service_result.data):
                            logger.debug(f"Tool {tool.name} {method_name} returned invalid data")
                            continue
                        # 处理服务结果
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
                                            "scanner": tool.name,
                                            "method": method_name
                                        })
                    except Exception as e:
                        logger.exception(f"Tool {tool.name} {method_name} failed")
                    break  # 找到一个有效方法就退出

            # 如果工具没有专用方法，尝试通用execute
            if not method_found and hasattr(tool, 'execute'):
                try:
                    result_obj = await tool.execute(target, {"profile": "service"})
                    if result_obj.success and result_obj.data:
                        for host in result_obj.data.get("hosts", []):
                            for svc in host.get("ports", []):
                                if svc.get("state") == "open":
                                    port = svc.get("port")
                                    if port in self.WEB_PORTS or (isinstance(port, int) and port < 1024):
                                        services.append({
                                            "port": port,
                                            "service": svc.get("service"),
                                            "version": "detected",
                                            "scanner": tool.name,
                                            "method": "execute"
                                        })
                except Exception as e:
                    logger.exception(f"Tool {tool.name} execute service detection failed")
        result["services"] = services
        return result
    async def _enumerate_subdomains(self, target: str) -> List[Dict[str, str]]:
        """
        异步枚举子域名

        实现思路：
        1. 先检测是否存在泛解析（Wildcard DNS）
        2. 并发解析所有常见子域名前缀
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
        random_sub = f"no-such-subdomain-{os.urandom(4).hex()}.{target}"
        wildcard_ip = None
        try:
            wildcard_ip = await loop.run_in_executor(None, socket.gethostbyname, random_sub)
            if wildcard_ip:
                logger.info(f"检测到泛解析: {target} -> {wildcard_ip}")
        except socket.gaierror:
            wildcard_ip = None
        # ==== 步骤2: 定义解析函数 ====
        async def resolve(prefix: str) -> Optional[Dict[str, str]]:
            subdomain = f"{prefix}.{target}"
            try:
                def _resolve():
                    try:
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