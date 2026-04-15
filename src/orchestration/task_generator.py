"""
Task Generator - 根据目标动态生成Tasks
"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum


class TaskType(Enum):
    """任务类型"""
    RECON = "recon"
    SCAN = "scan"
    EXPLOIT = "exploit"
    POST_EXPLOIT = "post_exploit"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    LATERAL_MOVEMENT = "lateral_movement"
    DATA_EXFILTRATION = "data_exfiltration"
    REPORT = "report"


@dataclass
class GeneratedTask:
    """生成的任务"""
    task_id: str
    task_type: TaskType
    name: str
    description: str
    agent: str
    dependencies: List[str] = field(default_factory=list)
    parameters: Dict[str, Any] = field(default_factory=dict)
    priority: int = 1


class TaskGenerator:
    """
    任务生成器
    
    根据目标特征和上下文动态生成任务序列
    """
    
    def __init__(self):
        self._templates: Dict[TaskType, Dict[str, Any]] = {}
        self._load_default_templates()
    
    def _load_default_templates(self) -> None:
        """加载默认任务模板"""
        self._templates = {
            TaskType.RECON: {
                "name": "Information Gathering",
                "description": "Gather information about the target",
                "agent": "recon_agent",
                "priority": 1
            },
            TaskType.SCAN: {
                "name": "Vulnerability Scanning",
                "description": "Scan for vulnerabilities",
                "agent": "recon_agent",
                "priority": 2
            },
            TaskType.EXPLOIT: {
                "name": "Exploit Vulnerabilities",
                "description": "Exploit discovered vulnerabilities",
                "agent": "exploit_agent",
                "priority": 3
            },
            TaskType.POST_EXPLOIT: {
                "name": "Post Exploitation",
                "description": "Perform post-exploitation activities",
                "agent": "exploit_agent",
                "priority": 4
            },
            TaskType.PRIVILEGE_ESCALATION: {
                "name": "Privilege Escalation",
                "description": "Escalate privileges on compromised system",
                "agent": "privilege_agent",
                "priority": 5
            },
            TaskType.REPORT: {
                "name": "Generate Report",
                "description": "Generate penetration test report",
                "agent": "report_agent",
                "priority": 99
            }
        }
    
    def generate_tasks(
        self,
        target: str,
        scope: List[str] = None,
        context: Dict[str, Any] = None
    ) -> List[GeneratedTask]:
        """
        根据目标生成任务序列
        
        Args:
            target: 目标地址
            scope: 测试范围
            context: 额外上下文
        
        Returns:
            任务列表
        """
        tasks = []
        task_id_counter = 1
        
        # 基础任务序列
        for task_type in [TaskType.RECON, TaskType.SCAN, TaskType.REPORT]:
            template = self._templates[task_type]
            task = GeneratedTask(
                task_id=f"task_{task_id_counter:03d}",
                task_type=task_type,
                name=template["name"],
                description=template["description"],
                agent=template["agent"],
                priority=template["priority"],
                parameters={"target": target, "scope": scope or []}
            )
            tasks.append(task)
            task_id_counter += 1
        
        return tasks
    
    def generate_from_findings(
        self,
        findings: List[Dict[str, Any]]
    ) -> List[GeneratedTask]:
        """
        根据发现生成后续任务
        
        Args:
            findings: 前序任务的发现
        
        Returns:
            新任务列表
        """
        tasks = []
        task_id_counter = 100  # 从100开始避免与基础任务冲突
        
        # 漏洞分类到任务类型的映射
        vuln_to_task_map = {
            "sqli": TaskType.EXPLOIT,
            "xss": TaskType.EXPLOIT,
            "rce": TaskType.EXPLOIT,
            "lfi": TaskType.EXPLOIT,
            "ssrf": TaskType.EXPLOIT,
            "default_creds": TaskType.EXPLOIT,
            "unauth_access": TaskType.EXPLOIT,
            "deserialization": TaskType.EXPLOIT,
            "eternalblue": TaskType.EXPLOIT,
            "bluekeep": TaskType.EXPLOIT,
            "log4shell": TaskType.EXPLOIT,
        }
        
        # 根据发现的漏洞类型生成利用任务
        exploit_targets = set()
        for finding in findings:
            vuln_type = finding.get("vuln_type", "")
            service = finding.get("service", "")
            target = finding.get("target", "")
            port = finding.get("port")
            severity = finding.get("severity", "LOW")
            
            # 确定任务类型
            task_type = vuln_to_task_map.get(vuln_type, TaskType.EXPLOIT)
            
            # 避免重复生成相同目标的利用任务
            target_key = f"{target}:{port}"
            if target_key not in exploit_targets:
                exploit_targets.add(target_key)
                
                task = GeneratedTask(
                    task_id=f"task_{task_id_counter:03d}",
                    task_type=task_type,
                    name=f"Exploit {vuln_type} on {target}:{port}",
                    description=f"利用 {vuln_type} 漏洞对 {target}:{port} 进行渗透测试",
                    agent="exploit_agent",
                    priority=1 if severity in ["CRITICAL", "HIGH"] else 2,
                    parameters={
                        "target": target,
                        "port": port,
                        "service": service,
                        "vuln_type": vuln_type,
                        "finding_id": finding.get("finding_id", ""),
                    }
                )
                tasks.append(task)
                task_id_counter += 1
        
        # 如果有成功的利用，生成后渗透任务
        successful_exploits = [f for f in findings if f.get("exploit_success", False)]
        if successful_exploits:
            for exploit in successful_exploits:
                task = GeneratedTask(
                    task_id=f"task_{task_id_counter:03d}",
                    task_type=TaskType.PRIVILEGE_ESCALATION,
                    name=f"Privilege Escalation on {exploit.get('target', 'unknown')}",
                    description="尝试提升已获取访问权限的级别",
                    agent="privilege_agent",
                    priority=1,
                    parameters={
                        "target": exploit.get("target", ""),
                        "access_type": exploit.get("access_type", "shell"),
                        "finding_id": exploit.get("finding_id", ""),
                    }
                )
                tasks.append(task)
                task_id_counter += 1
        
        # 如果有多个主机被攻破，生成横向移动任务
        compromised_hosts = set()
        for finding in findings:
            if finding.get("exploit_success", False):
                compromised_hosts.add(finding.get("target", ""))
        
        if len(compromised_hosts) > 1:
            task = GeneratedTask(
                task_id=f"task_{task_id_counter:03d}",
                task_type=TaskType.LATERAL_MOVEMENT,
                name="Lateral Movement",
                description="在已攻破的主机之间进行横向移动",
                agent="exploit_agent",
                priority=2,
                parameters={
                    "compromised_hosts": list(compromised_hosts),
                }
            )
            tasks.append(task)
            task_id_counter += 1
        
        return tasks
    
    def add_template(self, task_type: TaskType, template: Dict[str, Any]) -> None:
        """添加任务模板"""
        self._templates[task_type] = template
    
    def get_template(self, task_type: TaskType) -> Optional[Dict[str, Any]]:
        """获取任务模板"""
        return self._templates.get(task_type)
    
    def prioritize_tasks(self, tasks: List[GeneratedTask]) -> List[GeneratedTask]:
        """按优先级排序任务"""
        return sorted(tasks, key=lambda t: t.priority)
    
    def resolve_dependencies(
        self,
        tasks: List[GeneratedTask]
    ) -> List[GeneratedTask]:
        """
        解析任务依赖关系
        
        Args:
            tasks: 任务列表
        
        Returns:
            排序后的任务列表（拓扑排序）
        """
        # 构建依赖图
        task_map = {t.task_id: t for t in tasks}
        in_degree = {t.task_id: 0 for t in tasks}
        adj = {t.task_id: [] for t in tasks}
        
        for task in tasks:
            for dep_id in task.dependencies:
                if dep_id in task_map:
                    adj[dep_id].append(task.task_id)
                    in_degree[task.task_id] += 1
        
        # Kahn's 拓扑排序算法
        queue = [tid for tid, deg in in_degree.items() if deg == 0]
        sorted_tasks = []
        
        while queue:
            # 选择优先级最高的无依赖任务
            queue.sort(key=lambda tid: -task_map[tid].priority)
            current = queue.pop(0)
            sorted_tasks.append(task_map[current])
            
            for neighbor in adj[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        
        # 如果有循环依赖，添加剩余任务
        remaining = [t for t in tasks if t not in sorted_tasks]
        sorted_tasks.extend(sorted(remaining, key=lambda t: t.priority, reverse=True))
        
        return sorted_tasks