"""测试状态管理 - 结构化存储渗透测试发现"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any
import re
import json


@dataclass
class ServiceInfo:
    host: str
    port: int
    service: str
    version: Optional[str] = None
    banner: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VulnerabilityInfo:
    name: str
    severity: str
    host: Optional[str] = None
    port: Optional[int] = None
    description: Optional[str] = None
    evidence: Optional[str] = None
    cve: Optional[str] = None


@dataclass
class CredentialInfo:
    username: str
    password: Optional[str] = None
    hash: Optional[str] = None
    service: Optional[str] = None
    source: Optional[str] = None


@dataclass
class ExecutedStep:
    step: int
    phase: str
    query: str
    result: str
    result_summary: str
    verified: bool
    category: str
    timestamp: datetime = field(default_factory=datetime.now)


class TestState:
    """渗透测试状态管理器"""

    PHASES = [
        "reconnaissance",
        "scanning",
        "enumeration",
        "vulnerability",
        "exploitation",
        "post_exploitation",
        "reporting",
    ]

    def __init__(self):
        self.target: str = ""
        self.phase: str = "reconnaissance"
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None

        self.discovered_hosts: List[str] = []
        self.discovered_services: List[ServiceInfo] = []
        self.discovered_vulns: List[VulnerabilityInfo] = []
        self.discovered_creds: List[CredentialInfo] = []

        self.executed_steps: List[ExecutedStep] = []
        self.step_counter: int = 0

        self.notes: List[str] = []
        self.plan: Optional[Dict[str, Any]] = None

    def add_step(
        self, phase: str, query: str, result: str, verified: bool, category: str
    ):
        """记录执行步骤"""
        self.step_counter += 1
        summary = self._summarize_result(result)

        step = ExecutedStep(
            step=self.step_counter,
            phase=phase,
            query=query,
            result=result,
            result_summary=summary,
            verified=verified,
            category=category,
        )
        self.executed_steps.append(step)
        return step

    def _summarize_result(self, result: str, max_len: int = 200) -> str:
        """生成结果摘要"""
        if not result:
            return ""
        result = result.strip()
        if len(result) <= max_len:
            return result
        return result[:max_len] + "..."

    def extract_from_result(self, category: str, result: str):
        """从工具结果中提取结构化数据"""
        if not result:
            return

        result_lower = result.lower()

        if category == "information_collection":
            self._extract_hosts(result)

        elif category == "scanning":
            self._extract_ports(result)

        elif category == "enumeration":
            self._extract_enumeration_data(result)

        elif category in ["web_exploitation", "exploitation"]:
            self._extract_vulnerabilities(result)
            self._extract_credentials(result)

        elif category == "password_crypto":
            self._extract_credentials(result)

        self._extract_generic_vulnerabilities(result)

    def _extract_hosts(self, result: str):
        """提取主机信息"""
        patterns = [
            r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})",
        ]

        for pattern in patterns:
            matches = re.findall(pattern, result)
            for match in matches:
                if match not in self.discovered_hosts and match not in [
                    "0.0.0.0",
                    "127.0.0.1",
                    "255.255.255.255",
                ]:
                    self.discovered_hosts.append(match)

    def _extract_ports(self, result: str):
        """提取端口和服务信息"""
        patterns = [
            r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d+)\s+open\s+(\S+)(?:\s+(.+))?",
            r"PORT\s+(\d+)/(\w+)\s+(\w+)\s+(\S+)",
            r"(\d+)/tcp\s+open\s+(\S+)(?:\s+(.+))?",
        ]

        for pattern in patterns:
            matches = re.findall(pattern, result, re.IGNORECASE)
            for match in matches:
                try:
                    if len(match) >= 3:
                        if "." in match[0]:
                            host, port, service = match[0], int(match[1]), match[2]
                            version = match[3] if len(match) > 3 else None
                        else:
                            port = int(match[0])
                            service = match[2] if len(match) > 2 else match[1]
                            host = self.target
                            version = match[3] if len(match) > 3 else None

                        existing = [
                            s
                            for s in self.discovered_services
                            if s.host == host and s.port == port
                        ]
                        if not existing:
                            self.discovered_services.append(
                                ServiceInfo(
                                    host=host,
                                    port=port,
                                    service=service,
                                    version=version,
                                )
                            )
                except (ValueError, IndexError):
                    continue

    def _extract_enumeration_data(self, result: str):
        """提取枚举数据"""
        patterns = [
            (r"username[:\s]+(\S+)", "username"),
            (r"user[:\s]+(\S+)", "username"),
            (r"share[:\s]+(\S+)", "share"),
            (r"domain[:\s]+(\S+)", "domain"),
        ]

        for pattern, info_type in patterns:
            matches = re.findall(pattern, result, re.IGNORECASE)
            for match in matches:
                if info_type == "username" and match not in [
                    c.username for c in self.discovered_creds
                ]:
                    self.discovered_creds.append(
                        CredentialInfo(username=match, source="enumeration")
                    )

    def _extract_vulnerabilities(self, result: str):
        """提取漏洞信息"""
        vuln_patterns = [
            (r"(CVE-\d{4}-\d{4,})", "CVE"),
            (r"(SQL\s*injection)", "sqli", "high"),
            (r"(XSS|Cross-site scripting)", "xss", "medium"),
            (r"(Remote\s*code\s*execution|RCE)", "rce", "critical"),
            (r"(Directory\s*traversal)", "traversal", "medium"),
            (r"(Buffer\s*overflow)", "buffer_overflow", "high"),
            (r"(Authentication\s*bypass)", "auth_bypass", "high"),
            (r"(Default\s*credentials?)", "default_creds", "high"),
            (r"(Weak\s*password)", "weak_password", "medium"),
        ]

        for pattern_data in vuln_patterns:
            pattern = pattern_data[0]
            matches = re.findall(pattern, result, re.IGNORECASE)
            for match in matches:
                vuln_name = pattern_data[1] if len(pattern_data) > 1 else match
                severity = pattern_data[2] if len(pattern_data) > 2 else "medium"

                existing = [
                    v
                    for v in self.discovered_vulns
                    if v.name.lower() == str(vuln_name).lower()
                ]
                if not existing:
                    self.discovered_vulns.append(
                        VulnerabilityInfo(
                            name=str(vuln_name), severity=severity, evidence=match
                        )
                    )

    def _extract_credentials(self, result: str):
        """提取凭据信息"""
        patterns = [
            (r"(?:username|user|login)[:\s]+(\S+)", "username"),
            (r"(?:password|pass|pwd)[:\s]+(\S+)", "password"),
            (r"([a-f0-9]{32})", "md5_hash"),
            (r"([a-f0-9]{40})", "sha1_hash"),
            (r"\$([0-9])[a-z\$]?\$.+", "hash"),
        ]

        for pattern, cred_type in patterns:
            matches = re.findall(pattern, result, re.IGNORECASE)
            for match in matches:
                if cred_type == "username":
                    existing = [c for c in self.discovered_creds if c.username == match]
                    if not existing:
                        self.discovered_creds.append(CredentialInfo(username=match))
                elif cred_type == "password":
                    if self.discovered_creds and not self.discovered_creds[-1].password:
                        self.discovered_creds[-1].password = match
                elif cred_type in ["md5_hash", "sha1_hash", "hash"]:
                    existing = [c for c in self.discovered_creds if c.hash == match]
                    if not existing:
                        self.discovered_creds.append(
                            CredentialInfo(username="unknown", hash=match)
                        )

    def _extract_generic_vulnerabilities(self, result: str):
        """提取通用漏洞标记"""
        indicators = [
            ("vulnerable", "medium"),
            ("exploit", "high"),
            ("vulnerability", "medium"),
            ("vuln", "medium"),
            ("compromised", "critical"),
        ]

        result_lower = result.lower()
        for indicator, severity in indicators:
            if indicator in result_lower and not any(
                v.name.lower() == indicator for v in self.discovered_vulns
            ):
                context_match = re.search(
                    rf".{{0,50}}{indicator}.{{0,50}}", result, re.IGNORECASE
                )
                evidence = context_match.group(0) if context_match else indicator

                self.discovered_vulns.append(
                    VulnerabilityInfo(
                        name=f"potential_{indicator}",
                        severity=severity,
                        evidence=evidence,
                    )
                )
                break

    def get_phase_summary(self) -> Dict[str, Any]:
        """获取当前阶段摘要"""
        return {
            "target": self.target,
            "current_phase": self.phase,
            "total_steps": len(self.executed_steps),
            "hosts_found": len(self.discovered_hosts),
            "services_found": len(self.discovered_services),
            "vulns_found": len(self.discovered_vulns),
            "creds_found": len(self.discovered_creds),
        }

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "target": self.target,
            "phase": self.phase,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "hosts": self.discovered_hosts,
            "services": [
                {
                    "host": s.host,
                    "port": s.port,
                    "service": s.service,
                    "version": s.version,
                }
                for s in self.discovered_services
            ],
            "vulnerabilities": [
                {"name": v.name, "severity": v.severity, "evidence": v.evidence}
                for v in self.discovered_vulns
            ],
            "credentials": [
                {"username": c.username, "password": c.password, "hash": c.hash}
                for c in self.discovered_creds
            ],
            "executed_steps": [
                {
                    "step": s.step,
                    "phase": s.phase,
                    "query": s.query,
                    "verified": s.verified,
                    "category": s.category,
                }
                for s in self.executed_steps
            ],
        }

    def __str__(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)
