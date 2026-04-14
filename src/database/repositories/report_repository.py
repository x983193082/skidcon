"""
Report Repository - 报告数据访问层
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from ..db_models import Report, Scan
from .base import BaseRepository
class ReportRepository(BaseRepository[Report]):
    """报告 Repository"""
    def __init__(self, session: Session):
        super().__init__(Report, session)
    def create_report(
        self,
        report_id: str,
        scan_id: str,          # 业务标识 Scan.scan_id
        title: str = "",
        format: str = "pdf",
        **kwargs
    ) -> Report:
        """创建报告记录"""
        # 将业务 scan_id 转换为内部主键
        scan = self.session.query(Scan).filter(Scan.scan_id == scan_id).first()
        if not scan:
            raise ValueError(f"Scan with scan_id '{scan_id}' not found")
        return self.create(
            report_id=report_id,
            scan_id=scan.id,    # ✅ 存储内部主键
            title=title or f"Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            format=format,
            status="generating",
            **kwargs
        )
    def get_by_report_id(self, report_id: str) -> Optional[Report]:
        """通过业务 report_id 获取"""
        return self.get_by_field("report_id", report_id)
    def update_status(
        self,
        report_id: str,
        status: str,
        file_path: Optional[str] = None,
        file_size: Optional[int] = None,
        download_url: Optional[str] = None,
    ) -> Optional[Report]:
        """更新报告状态"""
        report = self.get_by_report_id(report_id)
        if not report:
            return None
        report.status = status
        if file_path is not None:
            report.file_path = file_path
        if file_size is not None:
            report.file_size = file_size
        if download_url is not None:
            report.download_url = download_url
        if status == "completed" and report.completed_at is None:
            report.completed_at = datetime.now()
        self.session.flush()
        return report
    def list_by_scan(self, scan_id: str) -> List[Report]:
        """获取扫描的所有报告（通过业务 scan_id）"""
        return self.session.query(Report).join(Scan).filter(
            Scan.scan_id == scan_id
        ).order_by(Report.created_at.desc()).all()
    def list_by_status(self, status: str, limit: int = 100) -> List[Report]:
        """按状态列表"""
        return self.session.query(Report).filter(
            Report.status == status
        ).order_by(Report.created_at.desc()).limit(limit).all()