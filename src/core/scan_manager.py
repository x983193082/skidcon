"""
Scan Manager - 扫描状态管理
管理扫描生命周期（创建/暂停/恢复/停止/结果）
"""

import json
import threading
import uuid
from enum import Enum
from typing import Any, Dict, Optional, List
from datetime import datetime

import redis
from loguru import logger

from .settings import get_settings
from .queue import TaskQueue, get_task_queue


class ScanStatus(Enum):
    """扫描状态"""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class ScanManager:
    """扫描管理器（线程安全单例）"""

    _instance: Optional["ScanManager"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self.task_queue = get_task_queue()
        settings = get_settings()
        self.scan_ttl = getattr(settings, "scan_ttl", 86400 * 7)
        self.scan_prefix = "scan"
        self.stats_key = f"{self.scan_prefix}:stats"
        # ====== 新增：SQLite 数据库 ======
        from ..database import Database
        self.db = Database.get_instance()
        # 注意：create_tables() 已在应用启动时统一调用，此处不再重复

    @classmethod
    def get_instance(cls) -> "ScanManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        with cls._lock:
            cls._instance = None

    @property
    def client(self) -> redis.Redis:
        self.task_queue._ensure_connection()
        return self.task_queue.client

    def _generate_scan_id(self) -> str:
        return f"scan_{uuid.uuid4().hex[:12]}"

    def _get_scan_key(self, scan_id: str) -> str:
        return f"{self.scan_prefix}:{scan_id}"

    def _get_findings_key(self, scan_id: str) -> str:
        return f"{self.scan_prefix}:{scan_id}:findings"

    def _validate_target(self, target: str) -> str:
        if not target or not target.strip():
            raise ValueError("Target cannot be empty")
        return target.strip()

    def _invalidate_stats_cache(self) -> None:
        try:
            self.client.delete(self.stats_key)
        except Exception as e:
            logger.debug(f"Failed to invalidate stats cache: {e}")

    def _update_stats_counter(self, status: str, delta: int = 1) -> None:
        """原子更新统计计数器（限制最小值为0）"""
        try:
            if delta < 0:
                current = self.client.hget(self.stats_key, status)
                current_val = int(current) if current else 0
                new_val = max(0, current_val + delta)
                self.client.hset(self.stats_key, status, new_val)
            else:
                self.client.hincrby(self.stats_key, status, delta)
        except Exception as e:
            logger.warning(f"Failed to update stats counter: {e}")

    def create_scan(
        self,
        target: str,
        scope: Optional[List[str]] = None,
        scan_type: str = "full",
        options: Optional[Dict[str, Any]] = None,
    ) -> str:
        target = self._validate_target(target)
        scan_id = self._generate_scan_id()
        scope = scope or []
        options = options or {}

        task_data = {
            "scan_id": scan_id,
            "task_type": "scan",
            "target": target,
            "scope": scope,
            "scan_type": scan_type,
            "options": options,
        }
        task_id = self.task_queue.enqueue(task_data, priority=0)

        scan_data = {
            "scan_id": scan_id,
            "task_id": task_id,
            "target": target,
            "scope": scope,
            "scan_type": scan_type,
            "options": options,
            "status": ScanStatus.PENDING.value,
            "created_at": datetime.now().isoformat(),
            "started_at": None,
            "completed_at": None,
            "current_phase": "init",
            "progress": 0,
            "findings_count": 0,
        }

        try:
            key = self._get_scan_key(scan_id)
            self.client.setex(key, self.scan_ttl, json.dumps(scan_data))
            self._update_stats_counter(ScanStatus.PENDING.value, 1)
            logger.info(f"Scan created: {scan_id} target={target} task_id={task_id}")
            return scan_id
        except Exception as e:
            logger.error(f"Failed to create scan: {e}")
            raise

    def get_status(self, scan_id: str) -> Optional[Dict[str, Any]]:
        try:
            key = self._get_scan_key(scan_id)
            data = self.client.get(key)
            return json.loads(data) if data else None
        except Exception as e:
            logger.error(f"Failed to get scan status: {e}")
            return None

    def pause(self, scan_id: str) -> bool:
        try:
            scan_data = self.get_status(scan_id)
            if not scan_data:
                logger.warning(f"Scan not found: {scan_id}")
                return False
            if scan_data["status"] != ScanStatus.RUNNING.value:
                logger.warning(f"Cannot pause scan in status: {scan_data['status']}")
                return False

            old_status = scan_data["status"]
            scan_data["status"] = ScanStatus.PAUSED.value
            scan_data["paused_at"] = datetime.now().isoformat()

            key = self._get_scan_key(scan_id)
            self.client.setex(key, self.scan_ttl, json.dumps(scan_data))

            self._update_stats_counter(old_status, -1)
            self._update_stats_counter(ScanStatus.PAUSED.value, 1)

            logger.info(f"Scan paused: {scan_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to pause scan: {e}")
            return False

    def resume(self, scan_id: str) -> bool:
        try:
            scan_data = self.get_status(scan_id)
            if not scan_data:
                logger.warning(f"Scan not found: {scan_id}")
                return False
            if scan_data["status"] != ScanStatus.PAUSED.value:
                logger.warning(f"Cannot resume scan in status: {scan_data['status']}")
                return False

            old_status = scan_data["status"]
            scan_data["status"] = ScanStatus.RUNNING.value
            scan_data["resumed_at"] = datetime.now().isoformat()

            task_data = {
                "scan_id": scan_id,
                "task_type": "resume",
                "target": scan_data["target"],
                "scope": scan_data.get("scope", []),
                "scan_type": scan_data.get("scan_type", "full"),
                "options": scan_data.get("options", {}),
            }
            task_id = self.task_queue.enqueue(task_data, priority=1)
            scan_data["task_id"] = task_id

            key = self._get_scan_key(scan_id)
            self.client.setex(key, self.scan_ttl, json.dumps(scan_data))

            self._update_stats_counter(old_status, -1)
            self._update_stats_counter(ScanStatus.RUNNING.value, 1)

            logger.info(f"Scan resumed: {scan_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to resume scan: {e}")
            return False

    def stop(self, scan_id: str) -> bool:
        try:
            scan_data = self.get_status(scan_id)
            if not scan_data:
                logger.warning(f"Scan not found: {scan_id}")
                return False

            old_status = scan_data["status"]
            scan_data["status"] = ScanStatus.STOPPED.value
            scan_data["stopped_at"] = datetime.now().isoformat()

            key = self._get_scan_key(scan_id)
            self.client.setex(key, self.scan_ttl, json.dumps(scan_data))

            self._update_stats_counter(old_status, -1)
            self._update_stats_counter(ScanStatus.STOPPED.value, 1)

            logger.info(f"Scan stopped: {scan_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to stop scan: {e}")
            return False

    def update_progress(self, scan_id: str, phase: str, progress: float) -> None:
        try:
            scan_data = self.get_status(scan_id)
            if scan_data:
                scan_data["current_phase"] = phase
                scan_data["progress"] = progress
                key = self._get_scan_key(scan_id)
                self.client.setex(key, self.scan_ttl, json.dumps(scan_data))
        except Exception as e:
            logger.error(f"Failed to update progress: {e}")

    def add_finding(self, scan_id: str, finding: Dict[str, Any]) -> None:
        try:
            key = self._get_findings_key(scan_id)
            self.client.rpush(key, json.dumps(finding))
            self.client.expire(key, self.scan_ttl)
        except Exception as e:
            logger.error(f"Failed to add finding: {e}")

    def get_findings(
        self, scan_id: str, limit: int = 100, offset: int = 0
    ) -> List[Dict[str, Any]]:
        findings = []
        try:
            key = self._get_findings_key(scan_id)
            start = offset
            end = offset + limit - 1
            for finding_json in self.client.lrange(key, start, end):
                findings.append(json.loads(finding_json))
        except Exception as e:
            logger.error(f"Failed to get findings: {e}")
        return findings

    def get_results(self, scan_id: str) -> Optional[Dict[str, Any]]:
        try:
            scan_data = self.get_status(scan_id)
            if not scan_data:
                return None

            findings = self.get_findings(scan_id, limit=1000)
            findings_count = self.client.llen(self._get_findings_key(scan_id))

            return {
                "scan_id": scan_id,
                "target": scan_data["target"],
                "status": scan_data["status"],
                "progress": scan_data.get("progress", 0),
                "current_phase": scan_data.get("current_phase", ""),
                "findings_count": findings_count,
                "findings": findings,
                "created_at": scan_data.get("created_at"),
                "started_at": scan_data.get("started_at"),
                "completed_at": scan_data.get("completed_at"),
            }
        except Exception as e:
            logger.error(f"Failed to get results: {e}")
            return None

    def mark_completed(self, scan_id: str, status: str = "completed") -> None:
        try:
            scan_data = self.get_status(scan_id)
            if scan_data:
                old_status = scan_data["status"]
                scan_data["status"] = status
                scan_data["completed_at"] = datetime.now().isoformat()
                scan_data["progress"] = 100
                key = self._get_scan_key(scan_id)
                self.client.setex(key, self.scan_ttl, json.dumps(scan_data))

                self._update_stats_counter(old_status, -1)
                self._update_stats_counter(status, 1)

                logger.info(f"Scan completed: {scan_id} status={status}")
        except Exception as e:
            logger.error(f"Failed to mark completed: {e}")

    def get_stats(self) -> Dict[str, int]:
        try:
            raw = self.client.hgetall(self.stats_key)
            if raw:
                return {k: int(v) for k, v in raw.items()}
        except Exception as e:
            logger.error(f"Failed to get stats from counter: {e}")

        stats = {
            "pending": 0,
            "running": 0,
            "paused": 0,
            "completed": 0,
            "failed": 0,
            "stopped": 0,
        }
        try:
            pattern = f"{self.scan_prefix}:*"
            for key in self.client.scan_iter(match=pattern, count=100):
                if ":findings" not in key:
                    data = self.client.get(key)
                    if data:
                        scan_data = json.loads(data)
                        status = scan_data.get("status", "pending")
                        if status in stats:
                            stats[status] += 1
            if stats:
                self.client.hset(self.stats_key, mapping=stats)
                self.client.expire(self.stats_key, 3600)
        except Exception as e:
            logger.error(f"Failed to rebuild stats: {e}")
        return stats

    def _save_scan_to_db(self, scan_data: dict):
        """同步扫描数据到 SQLite（最终一致性）"""
        from ..database.repositories import ScanRepository

        try:
            with self.db.get_session() as session:
                repo = ScanRepository(session)
                scan_id = scan_data.get("scan_id")
                existing = repo.get_by_scan_id(scan_id)

                if existing:
                    repo.update_status(
                        scan_id,
                        status=scan_data.get("status"),
                        progress=scan_data.get("progress"),
                        current_phase=scan_data.get("current_phase"),
                        findings_count=scan_data.get("findings_count"),
                    )
                else:
                    repo.create_scan(
                        scan_id=scan_id,
                        target=scan_data.get("target"),
                        scan_type=scan_data.get("scan_type"),
                        scope=scan_data.get("scope"),
                        task_id=scan_data.get("task_id"),
                    )
        except Exception as e:
            logger.warning(f"Failed to save scan to SQLite (scan_id={scan_id}): {e}")
            # 可选：写入死信队列供后续补偿

    def _save_findings_to_db(self, scan_id: str, findings: list):
        """同步发现数据到 SQLite（批量插入，最终一致性）"""
        from ..database.repositories import FindingRepository

        if not findings:
            return

        try:
            with self.db.get_session() as session:
                repo = FindingRepository(session)

                # 准备批量插入数据（传入业务 scan_id，repo 内部转换）
                findings_data = []
                for f in findings:
                    findings_data.append({
                        "scan_id": scan_id,  # 业务标识，非内部 ID
                        "title": f.get("title"),
                        "severity": f.get("severity"),
                        "target": f.get("target"),
                        "finding_id": f.get("finding_id"),
                        "description": f.get("description", ""),
                        "port": f.get("port"),
                        "service": f.get("service"),
                        "evidence": f.get("evidence", {}),
                        "recommendation": f.get("recommendation", ""),
                        "references": f.get("references", []),
                    })

                repo.bulk_create(findings_data)

        except Exception as e:
            logger.warning(f"Failed to save findings to SQLite (scan_id={scan_id}, count={len(findings)}): {e}")


def get_scan_manager() -> ScanManager:
    return ScanManager.get_instance()
