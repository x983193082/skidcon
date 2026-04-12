"""
Report Generator - 报告生成器
生成渗透测试报告（PDF/HTML/JSON/Markdown）
"""

import json
import os
import threading
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, List
from dataclasses import dataclass

import redis
from loguru import logger

from .settings import get_settings


class ReportFormat(Enum):
    """报告格式"""

    PDF = "pdf"
    HTML = "html"
    JSON = "json"
    MARKDOWN = "markdown"


class ReportStatus(Enum):
    """报告状态"""

    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ReportConfig:
    """报告配置"""

    scan_id: str
    format: ReportFormat = ReportFormat.PDF
    language: str = "zh-CN"
    include_raw: bool = False
    title: Optional[str] = None


class ReportGenerator:
    """报告生成器（线程安全单例）"""

    _instance: Optional["ReportGenerator"] = None
    _lock = threading.Lock()

    def __init__(self, redis_url: Optional[str] = None):
        settings = get_settings()
        self.redis_url = redis_url or settings.redis_url
        self.client: Optional[redis.Redis] = None

        self.report_ttl = 86400 * 30
        self.report_prefix = "report"
        self.output_dir = settings.report_output_dir
        self.template_dir = os.path.join(settings.config_dir, "templates")

        os.makedirs(self.output_dir, exist_ok=True)
        self._connect()

    @classmethod
    def get_instance(cls, redis_url: Optional[str] = None) -> "ReportGenerator":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(redis_url)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        with cls._lock:
            cls._instance = None

    def _connect(self) -> None:
        try:
            self.client = redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_keepalive=True,
                health_check_interval=30,
            )
            self.client.ping()
            logger.info("ReportGenerator connected to Redis")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    def _ensure_connection(self) -> None:
        if self.client is None:
            self._connect()
            return
        try:
            self.client.ping()
        except (redis.ConnectionError, redis.TimeoutError):
            logger.warning("Redis connection lost, reconnecting...")
            self._connect()

    def _generate_report_id(self) -> str:
        return f"report_{uuid.uuid4().hex[:12]}"

    def _get_report_key(self, report_id: str) -> str:
        return f"{self.report_prefix}:{report_id}"

    def create_report(
        self,
        scan_id: str,
        format: ReportFormat = ReportFormat.PDF,
        language: str = "zh-CN",
        include_raw: bool = False,
    ) -> str:
        """创建报告记录"""
        self._ensure_connection()
        report_id = self._generate_report_id()

        report_data = {
            "report_id": report_id,
            "scan_id": scan_id,
            "format": format.value,
            "language": language,
            "include_raw": include_raw,
            "status": ReportStatus.GENERATING.value,
            "created_at": datetime.now().isoformat(),
            "completed_at": None,
            "file_path": None,
            "file_size": None,
            "error": None,
        }

        try:
            key = self._get_report_key(report_id)
            self.client.setex(key, self.report_ttl, json.dumps(report_data))
            logger.info(f"Report created: {report_id} for scan {scan_id}")
            return report_id
        except Exception as e:
            logger.error(f"Failed to create report: {e}")
            raise

    def get_report(self, report_id: str) -> Optional[Dict[str, Any]]:
        """获取报告信息"""
        self._ensure_connection()
        try:
            key = self._get_report_key(report_id)
            data = self.client.get(key)
            return json.loads(data) if data else None
        except Exception as e:
            logger.error(f"Failed to get report: {e}")
            return None

    def generate(self, scan_id: str, config: ReportConfig) -> str:
        """生成报告（同步方法）"""
        report_id = self.create_report(
            scan_id=scan_id,
            format=config.format,
            language=config.language,
            include_raw=config.include_raw,
        )

        try:
            scan_data = self._get_scan_data(scan_id)
            if not scan_data:
                raise ValueError(f"Scan not found: {scan_id}")

            content = self._generate_content(scan_data, config)
            file_path = self._save_file(report_id, content, config.format)
            self._mark_completed(report_id, file_path)

            logger.info(f"Report generated: {report_id}")
            return report_id
        except Exception as e:
            logger.error(f"Failed to generate report: {e}")
            self._mark_failed(report_id, str(e))
            raise

    def _get_scan_data(self, scan_id: str) -> Optional[Dict[str, Any]]:
        """获取扫描数据"""
        try:
            from .scan_manager import get_scan_manager

            sm = get_scan_manager()
            return sm.get_results(scan_id)
        except Exception as e:
            logger.error(f"Failed to get scan data: {e}")
            return None

    def _generate_content(self, scan_data: Dict[str, Any], config: ReportConfig) -> Any:
        """生成报告内容"""
        format = config.format

        if format == ReportFormat.JSON:
            return json.dumps(scan_data, indent=2, ensure_ascii=False)
        elif format == ReportFormat.HTML:
            return self._generate_html(scan_data, config)
        elif format == ReportFormat.MARKDOWN:
            return self._generate_markdown(scan_data, config)
        elif format == ReportFormat.PDF:
            return self._generate_pdf(scan_data, config)
        return json.dumps(scan_data, indent=2, ensure_ascii=False)

    def _generate_html(self, scan_data: Dict[str, Any], config: ReportConfig) -> str:
        """生成 HTML 报告"""
        findings = scan_data.get("findings", [])

        severity_groups: Dict[str, List[Dict]] = {}
        for f in findings:
            severity = f.get("severity", "info")
            if severity not in severity_groups:
                severity_groups[severity] = []
            severity_groups[severity].append(f)

        findings_html = ""
        severity_names = {
            "critical": "严重",
            "high": "高危",
            "medium": "中危",
            "low": "低危",
            "info": "信息",
        }
        order = ["critical", "high", "medium", "low", "info"]
        sorted_severities = sorted(
            severity_groups.keys(),
            key=lambda x: (order.index(x) if x in order else len(order), x),
        )

        for severity in sorted_severities:
            items = severity_groups[severity]
            label = severity_names.get(severity, severity)
            findings_html += f"""<h3>{label} ({len(items)})</h3>
<ul>
"""
            for item in items:
                findings_html += f"""<li><strong>{item.get("title", "N/A")}</strong>
<br>目标: {item.get("target", "N/A")}
<br>描述: {item.get("description", "N/A")[:100]}...</li>
"""
            findings_html += "</ul>"

        title = config.title or "渗透测试报告"

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - {scan_data.get("target", "N/A")}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }}
        h1 {{ color: #333; border-bottom: 3px solid #e74c3c; padding-bottom: 10px; }}
        h2 {{ color: #666; border-bottom: 2px solid #ddd; padding-bottom: 10px; }}
        h3 {{ color: #e74c3c; margin-top: 30px; }}
        ul {{ list-style: none; padding: 0; }}
        li {{ background: #f9f9f9; margin: 10px 0; padding: 15px; border-left: 4px solid #e74c3c; }}
        .summary {{ background: #f0f0f0; padding: 20px; border-radius: 5px; margin-bottom: 30px; }}
        .critical {{ border-color: #e74c3c; }}
        .high {{ border-color: #e67e22; }}
        .medium {{ border-color: #f1c40f; }}
        .low {{ border-color: #3498db; }}
        .footer {{ margin-top: 50px; padding-top: 20px; border-top: 1px solid #ddd; color: #999; font-size: 12px; }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    <div class="summary">
        <p><strong>扫描目标:</strong> {scan_data.get("target", "N/A")}</p>
        <p><strong>发现数量:</strong> {len(findings)}</p>
        <p><strong>扫描状态:</strong> {scan_data.get("status", "N/A")}</p>
        <p><strong>扫描时间:</strong> {scan_data.get("created_at", "N/A")}</p>
    </div>
    {findings_html}
    <div class="footer">
        <p>Generated by Pentest Crew Platform</p>
    </div>
</body>
</html>"""
        return html

    def _generate_markdown(
        self, scan_data: Dict[str, Any], config: ReportConfig
    ) -> str:
        """生成 Markdown 报告"""
        findings = scan_data.get("findings", [])

        severity_groups: Dict[str, List[Dict]] = {}
        for f in findings:
            severity = f.get("severity", "info")
            if severity not in severity_groups:
                severity_groups[severity] = []
            severity_groups[severity].append(f)

        title = config.title or "渗透测试报告"
        md = f"""# {title}

**扫描目标**: {scan_data.get("target", "N/A")}
**发现数量**: {len(findings)}
**扫描状态**: {scan_data.get("status", "N/A")}

---

"""

        severity_names = {
            "critical": "严重",
            "high": "高危",
            "medium": "中危",
            "low": "低危",
            "info": "信息",
        }
        order = ["critical", "high", "medium", "low", "info"]
        sorted_severities = sorted(
            severity_groups.keys(),
            key=lambda x: (order.index(x) if x in order else len(order), x),
        )

        for severity in sorted_severities:
            items = severity_groups[severity]
            label = severity_names.get(severity, severity)
            md += f"""## {label} ({len(items)})

"""
            for item in items:
                md += f"""### {item.get("title", "N/A")}
- **目标**: {item.get("target", "N/A")}
- **描述**: {item.get("description", "N/A")}

---
"""
        return md

    def _generate_pdf(self, scan_data: Dict[str, Any], config: ReportConfig) -> bytes:
        """生成 PDF 报告（依赖 WeasyPrint）"""
        try:
            from weasyprint import HTML
        except ImportError as e:
            raise ImportError(
                "WeasyPrint is required for PDF generation. "
                "Please install it with: pip install weasyprint"
            ) from e

        html_content = self._generate_html(scan_data, config)
        return HTML(string=html_content).write_pdf()

    def _save_file(self, report_id: str, content: Any, format: ReportFormat) -> str:
        """保存报告文件"""
        ext = format.value
        filename = f"{report_id}.{ext}"
        filepath = os.path.join(self.output_dir, filename)

        if isinstance(content, bytes):
            with open(filepath, "wb") as f:
                f.write(content)
        else:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)

        logger.info(f"Report saved: {filepath}")
        return filepath

    def _mark_completed(self, report_id: str, file_path: str) -> None:
        """标记报告完成"""
        self._ensure_connection()
        try:
            report_data = self.get_report(report_id)
            if report_data:
                report_data["status"] = ReportStatus.COMPLETED.value
                report_data["completed_at"] = datetime.now().isoformat()
                report_data["file_path"] = file_path
                report_data["file_size"] = (
                    os.path.getsize(file_path) if os.path.exists(file_path) else 0
                )
                key = self._get_report_key(report_id)
                self.client.setex(key, self.report_ttl, json.dumps(report_data))
        except Exception as e:
            logger.error(f"Failed to mark completed: {e}")

    def _mark_failed(self, report_id: str, error: str) -> None:
        """标记报告失败"""
        self._ensure_connection()
        try:
            report_data = self.get_report(report_id)
            if report_data:
                report_data["status"] = ReportStatus.FAILED.value
                report_data["error"] = error
                key = self._get_report_key(report_id)
                self.client.setex(key, self.report_ttl, json.dumps(report_data))
        except Exception as e:
            logger.error(f"Failed to mark failed: {e}")


def get_report_generator() -> ReportGenerator:
    """获取报告生成器单例"""
    return ReportGenerator.get_instance()
