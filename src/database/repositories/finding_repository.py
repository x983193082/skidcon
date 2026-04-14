"""
Finding Repository - 发现数据访问层
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from ..db_models import Finding, Scan
from .base import BaseRepository


class FindingRepository(BaseRepository[Finding]):
    """发现 Repository"""

    def __init__(self, session: Session):
        super().__init__(Finding, session)

    def create_finding(
        self,
        scan_id: str,          # 业务标识 Scan.scan_id
        title: str,
        severity: str,
        target: str,
        finding_id: Optional[str] = None,
        description: str = "",
        port: Optional[int] = None,
        service: Optional[str] = None,
        evidence: Optional[Dict] = None,
        recommendation: str = "",
        references: Optional[List[str]] = None,
        **kwargs
    ) -> Optional[Finding]:
        """
        创建发现记录
        注意：scan_id 为业务标识，内部会转换为 Scan.id
        """
        # 获取 Scan 内部主键
        scan = self.session.query(Scan).filter(Scan.scan_id == scan_id).first()
        if not scan:
            raise ValueError(f"Scan with scan_id '{scan_id}' not found")

        return self.create(
            scan_id=scan.id,          # 存储内部主键
            finding_id=finding_id,
            title=title,
            description=description,
            severity=severity,
            target=target,
            port=port,
            service=service,
            evidence=evidence or {},
            recommendation=recommendation,
            references=references or [],
            **kwargs
        )

    def get_by_finding_id(self, finding_id: str) -> Optional[Finding]:
        """通过业务 finding_id 获取"""
        return self.get_by_field("finding_id", finding_id)

    def list_by_scan(
        self,
        scan_id: str,               # 业务标识
        severity: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Finding]:
        """获取扫描的所有发现（通过业务 scan_id）"""
        # 使用 JOIN 直接过滤业务标识，避免二次查询
        query = self.session.query(Finding).join(Scan).filter(
            Scan.scan_id == scan_id
        )
        if severity:
            query = query.filter(Finding.severity == severity)

        # 按严重程度排序（自定义顺序）
        severity_order = {
            "critical": 1, "high": 2, "medium": 3, "low": 4, "info": 5
        }
        order_case = case(severity_order, value=Finding.severity, else_=99)
        query = query.order_by(order_case, Finding.discovered_at.desc())

        return query.offset(offset).limit(limit).all()

    def count_by_scan(self, scan_id: str) -> int:
        """统计扫描的发现数量（业务 scan_id）"""
        return self.session.query(func.count(Finding.id)).join(Scan).filter(
            Scan.scan_id == scan_id
        ).scalar()

    def count_by_severity(self, scan_id: str) -> Dict[str, int]:
        """按严重程度统计（业务 scan_id）"""
        results = self.session.query(
            Finding.severity,
            func.count(Finding.id)
        ).join(Scan).filter(
            Scan.scan_id == scan_id
        ).group_by(Finding.severity).all()
        return {severity: count for severity, count in results}

    def bulk_create(self, findings_data: List[Dict]) -> List[Finding]:
        """
        批量创建发现（高性能方式）
        要求：findings_data 中的字典必须与 Finding 模型字段匹配
        """
        if not findings_data:
            return []

        # 使用 bulk_insert_mappings 避免 ORM 开销
        mappings = []
        for f in findings_data:
            # 可选：对 scan_id 进行转换（若为业务标识）
            if "scan_id" in f:
                scan = self.session.query(Scan).filter(Scan.scan_id == f["scan_id"]).first()
                if not scan:
                    raise ValueError(f"Scan '{f['scan_id']}' not found")
                f = f.copy()
                f["scan_id"] = scan.id
            mappings.append(f)

        self.session.bulk_insert_mappings(Finding, mappings)
        self.session.flush()
        # 注意：bulk_insert 不返回 ORM 对象，如有需要可重新查询
        return []   # 或返回根据条件查询的新对象列表