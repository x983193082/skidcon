"""
API Schemas - Pydantic数据模型
"""
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime
from enum import Enum


# ==================== 扫描相关 ====================

class ScanType(str, Enum):
    """扫描类型"""
    QUICK = "quick"
    FULL = "full"
    CUSTOM = "custom"


class ScanStatus(str, Enum):
    """扫描状态"""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class ScanRequest(BaseModel):
    """扫描请求"""
    target: str = Field(..., description="目标地址")
    scope: List[str] = Field(default_factory=list, description="测试范围")
    scan_type: ScanType = Field(default=ScanType.FULL, description="扫描类型")
    options: Dict[str, Any] = Field(default_factory=dict, description="扫描选项")


class ScanResponse(BaseModel):
    """扫描响应"""
    scan_id: str = Field(..., description="扫描任务ID")
    status: ScanStatus = Field(..., description="扫描状态")
    message: str = Field(default="", description="状态消息")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")


class ScanProgress(BaseModel):
    """扫描进度"""
    scan_id: str
    status: ScanStatus
    progress: float = Field(..., ge=0, le=100, description="进度百分比")
    current_phase: str = Field(default="", description="当前阶段")
    findings_count: int = Field(default=0, description="发现数量")
    started_at: Optional[datetime] = None
    estimated_completion: Optional[datetime] = None


# ==================== 任务相关 ====================

class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority(str, Enum):
    """任务优先级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TaskInfo(BaseModel):
    """任务信息"""
    task_id: str = Field(..., description="任务ID")
    name: str = Field(..., description="任务名称")
    description: str = Field(default="", description="任务描述")
    status: TaskStatus = Field(..., description="任务状态")
    priority: TaskPriority = Field(default=TaskPriority.MEDIUM, description="优先级")
    progress: float = Field(default=0, ge=0, le=100, description="进度")
    created_at: datetime = Field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


# ==================== 发现相关 ====================

class Severity(str, Enum):
    """漏洞严重程度"""
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Finding(BaseModel):
    """发现"""
    finding_id: str = Field(..., description="发现ID")
    title: str = Field(..., description="标题")
    description: str = Field(default="", description="描述")
    severity: Severity = Field(..., description="严重程度")
    target: str = Field(..., description="目标")
    evidence: Dict[str, Any] = Field(default_factory=dict, description="证据")
    recommendation: str = Field(default="", description="修复建议")
    references: List[str] = Field(default_factory=list, description="参考链接")
    discovered_at: datetime = Field(default_factory=datetime.now)


class Vulnerability(BaseModel):
    """漏洞"""
    vuln_id: str = Field(..., description="漏洞ID")
    name: str = Field(..., description="漏洞名称")
    cve_id: Optional[str] = Field(default=None, description="CVE编号")
    cvss_score: Optional[float] = Field(default=None, ge=0, le=10, description="CVSS分数")
    severity: Severity = Field(..., description="严重程度")
    affected_host: str = Field(..., description="受影响主机")
    affected_port: Optional[int] = Field(default=None, description="受影响端口")
    description: str = Field(default="", description="漏洞描述")
    solution: str = Field(default="", description="解决方案")
    references: List[str] = Field(default_factory=list, description="参考链接")
    exploit_available: bool = Field(default=False, description="是否有公开利用")
    discovered_at: datetime = Field(default_factory=datetime.now)


# ==================== 报告相关 ====================

class ReportInfo(BaseModel):
    """报告信息"""
    report_id: str = Field(..., description="报告ID")
    scan_id: str = Field(..., description="关联扫描ID")
    title: str = Field(default="", description="报告标题")
    format: str = Field(default="pdf", description="报告格式")
    status: str = Field(default="generating", description="生成状态")
    created_at: datetime = Field(default_factory=datetime.now)
    download_url: Optional[str] = None


class ExecutiveSummary(BaseModel):
    """执行摘要"""
    total_findings: int = Field(default=0, description="总发现数")
    critical_count: int = Field(default=0, description="严重漏洞数")
    high_count: int = Field(default=0, description="高危漏洞数")
    medium_count: int = Field(default=0, description="中危漏洞数")
    low_count: int = Field(default=0, description="低危漏洞数")
    info_count: int = Field(default=0, description="信息数量")
    risk_score: float = Field(default=0, ge=0, le=100, description="风险评分")
    summary_text: str = Field(default="", description="摘要文本")