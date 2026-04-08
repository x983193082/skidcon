# Pentest Crew - 渗透测试自动化平台
# 五层架构：Orchestration -> Agent -> Tool -> Knowledge -> Infrastructure

from .core import BaseAgent, BaseTool, BaseKnowledge, BaseTask
from .agents import ReconAgent, ExploitAgent, PrivilegeAgent, ReportAgent
from .tools import NmapWrapper, SQLMapWrapper
from .knowledge import VectorStore, CVEFetcher, AttackGraph
from .orchestration import CrewFactory, TaskGenerator, FlowController
from .utils import get_logger, setup_logging

__version__ = "1.0.0"
__author__ = "PentestCrew Team"

__all__ = [
    # Core
    "BaseAgent", "BaseTool", "BaseKnowledge", "BaseTask",
    # Agents
    "ReconAgent", "ExploitAgent", "PrivilegeAgent", "ReportAgent",
    # Tools
    "NmapWrapper", "SQLMapWrapper",
    # Knowledge
    "VectorStore", "CVEFetcher", "AttackGraph",
    # Orchestration
    "CrewFactory", "TaskGenerator", "FlowController",
    # Utils
    "get_logger", "setup_logging"
]
