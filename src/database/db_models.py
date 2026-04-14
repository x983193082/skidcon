"""
db_models.py - SQLAlchemy 数据模型
（外键指向主键，优化关系设计）
"""
import uuid
from datetime import datetime
from typing import List, Optional
from sqlalchemy import (
    Column, String, Integer, Float, Text, JSON, DateTime,
    ForeignKey, Index
)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func
Base = declarative_base()
def generate_uuid() -> str:
    """生成 UUID 字符串"""
    return str(uuid.uuid4())
class Scan(Base):
    """扫描记录表"""
    __tablename__ = "scans"
    # 主键
    id = Column(String(36), primary_key=True, default=generate_uuid)
    # 业务唯一标识（对外接口使用）
    scan_id = Column(String(36), unique=True, nullable=False, index=True, default=generate_uuid)
    target = Column(String(500), nullable=False)
    scope = Column(JSON, default=lambda: [])
    scan_type = Column(String(20), default="full")
    status = Column(String(20), default="pending", index=True)
    progress = Column(Float, default=0.0)
    current_phase = Column(String(50))
    findings_count = Column(Integer, default=0)
    task_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, default=func.now(), index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    # 关系
    findings = relationship(
        "Finding",
        back_populates="scan",
        cascade="all, delete-orphan",
        lazy="select"
    )
    reports = relationship(
        "Report",
        back_populates="scan",
        cascade="all, delete-orphan"
    )
    tasks = relationship(
        "Task",
        back_populates="scan",
        cascade="all, delete-orphan"
    )
    __table_args__ = (
        Index("idx_scan_status_created", "status", "created_at"),
        Index("idx_scan_target", "target"),
    )
class Finding(Base):
    """发现/漏洞表"""
    __tablename__ = "findings"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    # ✅ 优化：外键指向 scans.id（主键）
    scan_id = Column(
        String(36),
        ForeignKey("scans.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    # 业务标识（存储原始 scan_id 用于显示/查询）
    finding_id = Column(String(36), nullable=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, default="")
    severity = Column(String(20), index=True)
    target = Column(String(500))
    port = Column(Integer, nullable=True)
    service = Column(String(100), nullable=True)
    evidence = Column(JSON, default=lambda: {})
    recommendation = Column(Text, default="")
    references = Column(JSON, default=lambda: [])
    discovered_at = Column(DateTime, default=func.now())
    # 关系
    scan = relationship("Scan", back_populates="findings")
    __table_args__ = (
        Index("idx_finding_scan_severity", "scan_id", "severity"),
    )
class Task(Base):
    """任务表"""
    __tablename__ = "tasks"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(String(36), unique=True, nullable=False, index=True, default=generate_uuid)
    # ✅ 优化：外键指向 scans.id（主键）
    scan_id = Column(
        String(36),
        ForeignKey("scans.id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )
    task_type = Column(String(50))
    status = Column(String(20), default="pending", index=True)
    priority = Column(Integer, default=0)
    created_at = Column(DateTime, default=func.now(), index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)
    result_data = Column(JSON, default=lambda: {})
    # 关系
    scan = relationship("Scan", back_populates="tasks")
    history = relationship(
        "TaskHistory",
        back_populates="task",
        cascade="all, delete-orphan"
    )
    __table_args__ = (
        Index("idx_task_status_created", "status", "created_at"),
    )
class TaskHistory(Base):
    """任务历史（审计追踪）"""
    __tablename__ = "task_history"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    # ✅ 优化：外键指向 tasks.id（主键）
    task_id = Column(
        String(36),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    status = Column(String(20))
    changed_at = Column(DateTime, default=func.now())
    changed_by = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    # 关系
    task = relationship("Task", back_populates="history")
class Report(Base):
    """报告表"""
    __tablename__ = "reports"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    report_id = Column(String(36), unique=True, nullable=False, index=True, default=generate_uuid)
    # ✅ 优化：外键指向 scans.id（主键）
    scan_id = Column(
        String(36),
        ForeignKey("scans.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    title = Column(String(500))
    format = Column(String(20))
    status = Column(String(20))
    created_at = Column(DateTime, default=func.now())
    completed_at = Column(DateTime, nullable=True)
    file_path = Column(String(1000), nullable=True)
    file_size = Column(Integer, nullable=True)
    download_url = Column(String(1000), nullable=True)
    # 关系
    scan = relationship("Scan", back_populates="reports")
    __table_args__ = (
        Index("idx_report_scan", "scan_id"),
    )