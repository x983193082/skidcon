"""
Redis to SQLite 数据迁移脚本（最终完整版）
支持扫描、发现、任务、报告的全量迁移，包含分批提交、健壮解析、错误恢复
"""
import json
import re
from typing import Dict, List, Optional
import redis
from loguru import logger
from datetime import datetime

from ..core.settings import get_settings
from ..database import Database
from ..database.repositories import (
    ScanRepository,
    FindingRepository,
    TaskRepository,
    ReportRepository,
)


class RedisToSQLiteMigrator:
    """迁移器，封装迁移逻辑（最终版）"""

    def __init__(self):
        settings = get_settings()
        self.redis_client = redis.from_url(settings.redis_url, decode_responses=True)
        self.db = Database.get_instance()

    # ========== 工具方法 ==========
    @staticmethod
    def _parse_datetime(dt_str: str) -> Optional[datetime]:
        """安全解析多种 ISO 8601 日期格式"""
        if not dt_str:
            return None
        try:
            # 处理末尾 'Z' 为 '+00:00' 以支持 fromisoformat
            if dt_str.endswith("Z"):
                dt_str = dt_str[:-1] + "+00:00"
            return datetime.fromisoformat(dt_str)
        except ValueError:
            try:
                # 尝试使用 dateutil 解析更宽松的格式
                from dateutil import parser
                return parser.isoparse(dt_str)
            except ImportError:
                logger.warning(f"dateutil not installed, cannot parse: {dt_str}")
                return None
            except Exception:
                logger.warning(f"Unparseable datetime: {dt_str}")
                return None

    def _get_scan_id_from_key(self, key: str) -> str:
        """
        从 Redis 键安全提取 scan_id
        格式: scan:SCAN_ID 或 scan:SCAN_ID:findings
        """
        match = re.match(r"scan:([^:]+)(?::findings)?", key)
        return match.group(1) if match else ""

    def _get_task_id_from_key(self, key: str) -> str:
        """从 Redis 键提取 task_id (格式: pentest:task:TASK_ID)"""
        return key.replace("pentest:task:", "")

    def _get_report_id_from_key(self, key: str) -> str:
        """从 Redis 键提取 report_id (格式: report:REPORT_ID)"""
        return key.replace("report:", "")

    def _parse_redis_scan_data(self, key: str) -> Optional[Dict]:
        """
        解析 Redis 中的扫描数据
        优先作为 Hash 读取，失败时尝试作为 JSON String 回退
        """
        try:
            # 尝试 Hash 结构
            if self.redis_client.type(key) == "hash" or not self.redis_client.type(key):
                data = self.redis_client.hgetall(key)
                if data:
                    # 转换数值字段
                    if "progress" in data:
                        data["progress"] = float(data["progress"])
                    if "findings_count" in data:
                        data["findings_count"] = int(data["findings_count"])
                    if "scope" in data and data["scope"]:
                        try:
                            data["scope"] = json.loads(data["scope"])
                        except json.JSONDecodeError:
                            data["scope"] = []
                    return data

            # 回退：尝试 String JSON
            raw = self.redis_client.get(key)
            if raw:
                return json.loads(raw)
        except Exception as e:
            logger.error(f"Failed to parse scan data from key {key}: {e}")
        return None

    # ========== 迁移方法 ==========
    def migrate_scans(self, batch_size: int = 100) -> int:
        """迁移扫描数据，分批提交以控制事务大小"""
        logger.info("Starting scan migration...")
        count = 0
        failed = 0

        # 扫描主键：排除 :findings 后缀
        scan_keys = [
            key for key in self.redis_client.scan_iter("scan:*")
            if not key.endswith(":findings")
        ]

        session = self.db.SessionLocal()
        repo = ScanRepository(session)

        for i, key in enumerate(scan_keys, 1):
            data = self._parse_redis_scan_data(key)
            if not data:
                failed += 1
                continue

            scan_id = data.get("scan_id") or self._get_scan_id_from_key(key)
            if not scan_id:
                logger.warning(f"No scan_id for key {key}")
                failed += 1
                continue

            try:
                existing = repo.get_by_scan_id(scan_id)
                if existing:
                    # 更新状态
                    repo.update_status(
                        scan_id,
                        status=data.get("status", "pending"),
                        progress=data.get("progress"),
                        current_phase=data.get("current_phase"),
                        findings_count=data.get("findings_count"),
                    )
                    # 手动更新时间戳
                    started = self._parse_datetime(data.get("started_at"))
                    if started:
                        existing.started_at = started
                    completed = self._parse_datetime(data.get("completed_at"))
                    if completed:
                        existing.completed_at = completed
                else:
                    # 创建新记录
                    repo.create_scan(
                        scan_id=scan_id,
                        target=data.get("target", ""),
                        scan_type=data.get("scan_type", "full"),
                        scope=data.get("scope", []),
                        task_id=data.get("task_id"),
                    )
                    # 立即更新状态
                    repo.update_status(
                        scan_id,
                        status=data.get("status", "pending"),
                        progress=data.get("progress"),
                        current_phase=data.get("current_phase"),
                        findings_count=data.get("findings_count"),
                    )
                    # 设置时间戳
                    scan_obj = repo.get_by_scan_id(scan_id)
                    if scan_obj:
                        started = self._parse_datetime(data.get("started_at"))
                        if started:
                            scan_obj.started_at = started
                        completed = self._parse_datetime(data.get("completed_at"))
                        if completed:
                            scan_obj.completed_at = completed

                count += 1

            except Exception as e:
                logger.error(f"Failed to migrate scan {scan_id}: {e}")
                failed += 1

            # 分批提交
            if i % batch_size == 0:
                session.commit()
                session.close()
                session = self.db.SessionLocal()
                repo = ScanRepository(session)

        session.commit()
        session.close()
        logger.info(f"Scan migration completed: {count} succeeded, {failed} failed")
        return count

    def migrate_findings(self) -> int:
        """迁移发现数据（批量插入优化）"""
        logger.info("Starting findings migration...")
        count = 0
        failed = 0

        for key in self.redis_client.scan_iter("scan:*:findings"):
            scan_id = self._get_scan_id_from_key(key)
            findings_data = self.redis_client.lrange(key, 0, -1)

            if not findings_data:
                continue

            findings = []
            for f_str in findings_data:
                try:
                    findings.append(json.loads(f_str))
                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON for scan {scan_id}: {e}")
                    failed += 1

            if not findings:
                continue

            try:
                with self.db.get_session() as session:
                    repo = FindingRepository(session)
                    bulk_data = []
                    for f in findings:
                        bulk_data.append({
                            "scan_id": scan_id,
                            "title": f.get("title", ""),
                            "severity": f.get("severity", "info"),
                            "target": f.get("target", ""),
                            "finding_id": f.get("finding_id"),
                            "description": f.get("description", ""),
                            "port": f.get("port"),
                            "service": f.get("service"),
                            "evidence": f.get("evidence", {}),
                            "recommendation": f.get("recommendation", ""),
                            "references": f.get("references", []),
                        })
                    repo.bulk_create(bulk_data)
                    count += len(bulk_data)
            except Exception as e:
                logger.error(f"Failed to migrate findings for scan {scan_id}: {e}")
                failed += len(findings)

        logger.info(f"Findings migration completed: {count} succeeded, {failed} failed")
        return count

    def migrate_tasks(self) -> int:
        """迁移任务数据"""
        logger.info("Starting task migration...")
        count = 0
        failed = 0

        for key in self.redis_client.scan_iter("pentest:task:*"):
            task_id = self._get_task_id_from_key(key)

            try:
                raw = self.redis_client.get(key)
                if not raw:
                    continue
                data = json.loads(raw)
            except Exception as e:
                logger.error(f"Failed to parse task data from {key}: {e}")
                failed += 1
                continue

            if not task_id:
                task_id = data.get("task_id")
            if not task_id:
                continue

            try:
                with self.db.get_session() as session:
                    repo = TaskRepository(session)
                    existing = repo.get_by_task_id(task_id)

                    # 提取 scan_id（兼容嵌套结构）
                    scan_id = data.get("scan_id") or data.get("data", {}).get("scan_id")

                    if not existing:
                        repo.create_task(
                            task_id=task_id,
                            task_type=data.get("task_type") or data.get("data", {}).get("task_type", "unknown"),
                            scan_id=scan_id,
                            priority=data.get("priority", 0),
                        )

                    # 更新状态及时间
                    repo.update_status(
                        task_id,
                        status=data.get("status", "pending"),
                        error=data.get("error") or data.get("last_error"),
                        result_data=data.get("result"),
                    )

                    # 补充时间戳（若 update_status 未处理）
                    task_obj = repo.get_by_task_id(task_id)
                    if task_obj:
                        started = self._parse_datetime(data.get("started_at"))
                        if started:
                            task_obj.started_at = started
                        completed = self._parse_datetime(data.get("completed_at"))
                        if completed:
                            task_obj.completed_at = completed

                    count += 1
            except Exception as e:
                logger.error(f"Failed to migrate task {task_id}: {e}")
                failed += 1

        logger.info(f"Task migration completed: {count} succeeded, {failed} failed")
        return count

    def migrate_reports(self) -> int:
        """迁移报告数据"""
        logger.info("Starting report migration...")
        count = 0
        failed = 0

        for key in self.redis_client.scan_iter("report:*"):
            report_id = self._get_report_id_from_key(key)

            try:
                raw = self.redis_client.get(key)
                if not raw:
                    continue
                data = json.loads(raw)
            except Exception as e:
                logger.error(f"Failed to parse report data from {key}: {e}")
                failed += 1
                continue

            if not report_id:
                report_id = data.get("report_id")
            if not report_id:
                continue

            try:
                with self.db.get_session() as session:
                    repo = ReportRepository(session)
                    existing = repo.get_by_report_id(report_id)

                    if not existing:
                        repo.create_report(
                            report_id=report_id,
                            scan_id=data.get("scan_id"),
                            title=data.get("title", ""),
                            format=data.get("format", "pdf"),
                        )

                    # 更新状态及文件信息
                    repo.update_status(
                        report_id,
                        status=data.get("status", "generating"),
                        file_path=data.get("file_path"),
                        file_size=data.get("file_size"),
                    )

                    # 手动设置 completed_at（若 Repository 未支持）
                    report_obj = repo.get_by_report_id(report_id)
                    if report_obj:
                        completed = self._parse_datetime(data.get("completed_at"))
                        if completed:
                            report_obj.completed_at = completed

                    count += 1
            except Exception as e:
                logger.error(f"Failed to migrate report {report_id}: {e}")
                failed += 1

        logger.info(f"Report migration completed: {count} succeeded, {failed} failed")
        return count

    def update_findings_counts(self):
        """修正扫描的 findings_count 字段（使用 SQL 批量更新）"""
        logger.info("Updating findings counts...")
        try:
            with self.db.get_session() as session:
                from ..database.db_models import Scan, Finding
                from sqlalchemy import func

                subq = session.query(
                    Finding.scan_id,
                    func.count(Finding.id).label("cnt")
                ).group_by(Finding.scan_id).subquery()

                session.query(Scan).outerjoin(
                    subq, Scan.id == subq.c.scan_id
                ).update(
                    {Scan.findings_count: func.coalesce(subq.c.cnt, 0)},
                    synchronize_session=False
                )
                session.commit()
            logger.info("Findings counts updated successfully")
        except Exception as e:
            logger.error(f"Failed to update findings counts: {e}")

    def migrate_all(self) -> Dict[str, int]:
        """执行所有迁移，保证数据一致性和最终计数修正"""
        logger.info("=== Starting full migration from Redis to SQLite ===")

        scans = self.migrate_scans()
        findings = self.migrate_findings()
        tasks = self.migrate_tasks()
        reports = self.migrate_reports()

        # 修正扫描的发现计数（因为迁移时 findings_count 可能不准确）
        self.update_findings_counts()

        result = {
            "scans": scans,
            "findings": findings,
            "tasks": tasks,
            "reports": reports,
        }
        logger.info(f"=== Migration completed: {result} ===")
        return result


def migrate_all():
    """便捷函数：执行全部迁移"""
    migrator = RedisToSQLiteMigrator()
    return migrator.migrate_all()


if __name__ == "__main__":
    migrate_all()