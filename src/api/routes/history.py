"""
History API - 历史数据查询接口
"""

from typing import Optional, List, Dict
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from datetime import datetime

from ...database import Database, get_database
from ...database.repositories import (
    ScanRepository,
    FindingRepository,
    TaskRepository,
    ReportRepository,
)

router = APIRouter(prefix="/history", tags=["历史数据"])


# ========== 响应模型 ==========
class ScanHistoryItem(BaseModel):
    scan_id: str
    target: str
    status: str
    progress: float
    current_phase: str = ""
    findings_count: int
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class FindingHistoryItem(BaseModel):
    finding_id: Optional[str] = None
    title: str
    severity: str
    target: str
    port: Optional[int] = None
    service: Optional[str] = None
    description: str = ""
    recommendation: str = ""

    class Config:
        from_attributes = True


class StatisticsResponse(BaseModel):
    total_scans: int
    by_status: Dict[str, int]
    total_findings: int
    by_severity: Dict[str, int]


# ========== API 端点 ==========
@router.get("/scans", response_model=List[ScanHistoryItem])
async def get_scan_history(
    status: Optional[str] = Query(None, description="按状态过滤"),
    target: Optional[str] = Query(None, description="按目标搜索"),
    scan_type: Optional[str] = Query(None, description="按扫描类型过滤"),
    limit: int = Query(100, ge=1, le=1000, description="返回数量限制"),
    offset: int = Query(0, ge=0, description="偏移量"),
    db: Database = Depends(get_database),
):
    """获取扫描历史"""
    with db.get_session() as session:
        repo = ScanRepository(session)

        if status:
            scans = repo.list_by_status(status, limit, offset)
        elif target or scan_type:
            scans = repo.search(
                target=target,
                status=status,
                scan_type=scan_type,
                limit=limit,
                offset=offset,
            )
        else:
            scans = repo.list_recent(limit, offset)

        return [
            ScanHistoryItem(
                scan_id=s.scan_id,
                target=s.target,
                status=s.status,
                progress=s.progress,
                current_phase=s.current_phase or "",
                findings_count=s.findings_count,
                created_at=s.created_at,
                started_at=s.started_at,
                completed_at=s.completed_at,
            )
            for s in scans
        ]


@router.get("/scans/{scan_id}/findings", response_model=List[FindingHistoryItem])
async def get_scan_findings(
    scan_id: str,
    severity: Optional[str] = Query(None, description="按严重程度过滤"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Database = Depends(get_database),
):
    """获取扫描的所有发现"""
    with db.get_session() as session:
        scan_repo = ScanRepository(session)
        scan = scan_repo.get_by_scan_id(scan_id)
        if not scan:
            raise HTTPException(status_code=404, detail=f"Scan '{scan_id}' not found")

        finding_repo = FindingRepository(session)
        findings = finding_repo.list_by_scan(scan_id, severity, limit, offset)

        return [
            FindingHistoryItem(
                finding_id=f.finding_id,
                title=f.title,
                severity=f.severity,
                target=f.target,
                port=f.port,
                service=f.service,
                description=f.description or "",
                recommendation=f.recommendation or "",
            )
            for f in findings
        ]


@router.get("/scans/{scan_id}/reports")
async def get_scan_reports(
    scan_id: str,
    db: Database = Depends(get_database),
):
    """获取扫描的所有报告"""
    with db.get_session() as session:
        scan_repo = ScanRepository(session)
        scan = scan_repo.get_by_scan_id(scan_id)
        if not scan:
            raise HTTPException(status_code=404, detail=f"Scan '{scan_id}' not found")

        repo = ReportRepository(session)
        reports = repo.list_by_scan(scan_id)

        return [
            {
                "report_id": r.report_id,
                "title": r.title,
                "format": r.format,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                "download_url": r.download_url,
            }
            for r in reports
        ]


@router.get("/statistics", response_model=StatisticsResponse)
async def get_statistics(db: Database = Depends(get_database)):
    """获取全局统计数据"""
    with db.get_session() as session:
        scan_repo = ScanRepository(session)
        scan_stats = scan_repo.get_statistics()

        from sqlalchemy import func
        from ...database.db_models import Finding

        severity_counts = (
            session.query(Finding.severity, func.count(Finding.id))
            .group_by(Finding.severity)
            .all()
        )
        by_severity = {sev: cnt for sev, cnt in severity_counts}

        total_findings = sum(by_severity.values())

        return StatisticsResponse(
            total_scans=scan_stats["total"],
            by_status=scan_stats["by_status"],
            total_findings=total_findings,
            by_severity=by_severity,
        )


@router.get("/tasks")
async def get_task_history(
    status: Optional[str] = Query(None),
    scan_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Database = Depends(get_database),
):
    """获取任务历史"""
    with db.get_session() as session:
        repo = TaskRepository(session)

        if scan_id:
            tasks = repo.list_by_scan(scan_id)
        elif status:
            tasks = repo.list_by_status(status, limit)
        else:
            tasks = repo.all(limit=limit, offset=offset)

        return [
            {
                "task_id": t.task_id,
                "task_type": t.task_type,
                "status": t.status,
                "priority": t.priority,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                "error": t.error,
            }
            for t in tasks
        ]
