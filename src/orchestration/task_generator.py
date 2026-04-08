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
        # TODO: 实现基于发现的任务生成
        raise NotImplementedError("Finding-based task generation pending")
    
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
        # TODO: 实现拓扑排序
        raise NotImplementedError("Dependency resolution pending")