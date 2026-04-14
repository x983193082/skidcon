"""
Scan Repository - 扫描数据访问层
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..db_models import Scan
from .base import BaseRepository


class ScanRepository(BaseRepository[Scan]):
    """扫描 Repository"""

    def __init__(self, session: Session):
        super().__init__(Scan, session)

    def create_scan(
        self,
        scan_id: str,
        target: str,
        scan_type: str = "full",
        scope: Optional[List] = None,          # ✅ 修正类型注解
        task_id: Optional[str] = None,
        **kwargs
    ) -> Scan:
        """创建扫描记录"""
        return self.create(
            scan_id=scan_id,
            target=target,
            scan_type=scan_type,
            scope=scope or [],
            task_id=task_id,
            status="pending",
            progress=0.0,
            current_phase="init",
            findings_count=0,
            **kwargs
        )

    def get_by_scan_id(self, scan_id: str) -> Optional[Scan]:
        """通过业务 scan_id 获取"""
        return self.get_by_field("scan_id", scan_id)

    def update_status(
        self,
        scan_id: str,
        status: str,
        progress: Optional[float] = None,
        current_phase: Optional[str] = None,
        findings_count: Optional[int] = None,
    ) -> Optional[Scan]:
        """
        更新扫描状态
        注：findings_count 应大于等于 0，不会自动校验
        """
        scan = self.get_by_scan_id(scan_id)
        if scan:
            scan.status = status
            if progress is not None:
                scan.progress = progress
            if current_phase is not None:
                scan.current_phase = current_phase
            if findings_count is not None:
                scan.findings_count = findings_count
            if status == "running" and scan.started_at is None:
                scan.started_at = datetime.now()
            if status in ["completed", "failed", "stopped"]:
                scan.completed_at = datetime.now()
            self.session.flush()
        return scan

    def list_by_status(
        self,
        status: str,
        limit: int = 100,   # 明确默认限制，避免返回大量数据
        offset: int = 0
    ) -> List[Scan]:
        """按状态列表（按创建时间倒序）"""
        return self.session.query(Scan).filter(
            Scan.status == status
        ).order_by(Scan.created_at.desc()).offset(offset).limit(limit).all()

    def list_recent(
        self,
        limit: int = 10,
        offset: int = 0
    ) -> List[Scan]:
        """获取最近的扫描"""
        return self.session.query(Scan).order_by(
            Scan.created_at.desc()
        ).offset(offset).limit(limit).all()

    def search(
        self,
        target: Optional[str] = None,
        status: Optional[str] = None,
        scan_type: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Scan]:
        """高级搜索（target 支持不区分大小写的模糊匹配）"""
        query = self.session.query(Scan)
        if target:
            query = query.filter(Scan.target.ilike(f"%{target}%"))   # ✅ 不区分大小写
        if status:
            query = query.filter(Scan.status == status)
        if scan_type:
            query = query.filter(Scan.scan_type == scan_type)
        if start_date:
            query = query.filter(Scan.created_at >= start_date)
        if end_date:
            query = query.filter(Scan.created_at <= end_date)
        return query.order_by(Scan.created_at.desc()).offset(offset).limit(limit).all()

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计数据"""
        total = self.session.query(func.count(Scan.id)).scalar()
        by_status = self.session.query(
            Scan.status,
            func.count(Scan.id).label("count")   # ✅ 添加标签提升可读性
        ).group_by(Scan.status).all()
        return {
            "total": total,
            "by_status": {status: count for status, count in by_status}
        }