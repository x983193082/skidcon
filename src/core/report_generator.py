"""
Report Generator - 报告生成器
生成渗透测试报告（PDF/HTML/JSON/Markdown）

修正版本：
- 修复 HTML 回退中的 XSS 漏洞
- 添加 Redis 连接关闭机制
- 增强重连逻辑的健壮性
- 细化异常捕获类型
- 添加文件路径安全校验
- 改进线程安全性
"""

import html
import json
import os
import re
import threading
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, List
from dataclasses import dataclass

import redis
from jinja2 import Environment, FileSystemLoader, select_autoescape, TemplateNotFound, TemplateError
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
    template: Optional[str] = "default"


class ReportGenerator:
    """报告生成器（线程安全单例）"""

    _instance: Optional["ReportGenerator"] = None
    _lock = threading.RLock()  # 使用可重入锁增强线程安全

    def __init__(self, redis_url: Optional[str] = None):
        settings = get_settings()
        self.redis_url = redis_url or settings.redis_url
        self.client: Optional[redis.Redis] = None
        self.report_ttl = 86400 * 30
        self.report_prefix = "report"
        self.output_dir = settings.report_output_dir
        self.template_dir = os.path.join(settings.config_dir, "templates", "report")
        self.jinja_env = Environment(
            loader=FileSystemLoader(self.template_dir),
            autoescape=select_autoescape(['html', 'xml']),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        os.makedirs(self.output_dir, exist_ok=True)
        self._connect()

    @classmethod
    def get_instance(cls, redis_url: Optional[str] = None) -> "ReportGenerator":
        """
        获取单例实例（线程安全）

        注意：首次调用时传入的 redis_url 将固定为该实例的配置，
        后续调用若传入不同 redis_url 将被忽略（符合单例预期）。
        若确实需要更改配置，请先调用 reset_instance()。
        """
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(redis_url)
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例实例（主要用于测试）"""
        with cls._lock:
            if cls._instance is not None:
                cls._instance.close()
                cls._instance = None

    def _connect(self) -> None:
        """建立 Redis 连接"""
        try:
            # 若已存在连接，先关闭旧连接（释放资源）
            if self.client:
                self.client.close()
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
        """确保 Redis 连接可用，若断开则自动重连"""
        if self.client is None:
            with self._lock:
                if self.client is None:
                    self._connect()
            return
        try:
            self.client.ping()
        except redis.RedisError:  # 捕获所有 Redis 异常
            logger.warning("Redis connection lost, reconnecting...")
            with self._lock:
                try:
                    self._connect()
                except Exception as e:
                    logger.error(f"Failed to reconnect to Redis: {e}")
                    raise

    def close(self) -> None:
        """关闭 Redis 连接，释放资源"""
        if self.client:
            try:
                self.client.close()
                logger.info("ReportGenerator Redis connection closed")
            except Exception as e:
                logger.warning(f"Error closing Redis connection: {e}")
            finally:
                self.client = None

    def __del__(self):
        """析构时尝试关闭连接"""
        self.close()

    # ==================== 报告 ID 与 Key 生成 ====================

    @staticmethod
    def _generate_report_id() -> str:
        """生成唯一报告 ID（仅包含字母数字）"""
        return f"report_{uuid.uuid4().hex[:12]}"

    def _get_report_key(self, report_id: str) -> str:
        """生成 Redis 存储键"""
        # 简单校验防止键注入（虽然 ID 是内部生成，但保持防御性）
        if not re.match(r'^[a-zA-Z0-9_]+$', report_id):
            raise ValueError(f"Invalid report_id: {report_id}")
        return f"{self.report_prefix}:{report_id}"

    # ==================== 报告元数据操作 ====================

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

    # ==================== 报告生成主流程 ====================

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
        """获取扫描数据（延迟导入避免循环依赖）"""
        try:
            from .scan_manager import get_scan_manager
            sm = get_scan_manager()
            return sm.get_results(scan_id)
        except Exception as e:
            logger.error(f"Failed to get scan data: {e}")
            return None

    # ==================== 报告内容生成 ====================

    def _generate_content(self, scan_data: Dict[str, Any], config: ReportConfig) -> Any:
        """根据格式生成报告内容"""
        format_handlers = {
            ReportFormat.JSON: self._generate_json,
            ReportFormat.HTML: self._generate_html,
            ReportFormat.MARKDOWN: self._generate_markdown,
            ReportFormat.PDF: self._generate_pdf,
        }
        handler = format_handlers.get(config.format)
        if handler is None:
            raise ValueError(f"Unsupported format: {config.format}")
        return handler(scan_data, config)

    def _generate_json(self, scan_data: Dict[str, Any], config: ReportConfig) -> str:
        """生成 JSON 报告"""
        return json.dumps(scan_data, indent=2, ensure_ascii=False)

    # ==================== 模板与上下文构建 ====================

    def _render_template(self, template_name: str, context: dict) -> str:
        """渲染 Jinja2 模板"""
        template = self.jinja_env.get_template(template_name)
        return template.render(**context)

    def _build_template_context(self, scan_data: Dict[str, Any], config: ReportConfig) -> Dict[str, Any]:
        """构建模板上下文（用于 HTML/Markdown）"""
        findings = scan_data.get("findings", [])
        severity_names = {
            "critical": "严重",
            "high": "高危",
            "medium": "中危",
            "low": "低危",
            "info": "信息",
        }
        severity_order = ["critical", "high", "medium", "low", "info"]

        # 按严重性分组
        severity_groups: Dict[str, List[Dict]] = {}
        for f in findings:
            severity = f.get("severity", "info")
            if severity not in severity_groups:
                severity_groups[severity] = []
            severity_groups[severity].append(f)

        # 按严重性顺序排序分组
        sorted_severities = sorted(
            severity_groups.keys(),
            key=lambda x: (severity_order.index(x) if x in severity_order else len(severity_order), x),
        )
        grouped_findings = []
        for severity in sorted_severities:
            items = severity_groups[severity]
            grouped_findings.append({
                "severity": severity,
                "label": severity_names.get(severity, severity),
                "count": len(items),
                "findings": items,
            })

        return {
            "title": config.title or "渗透测试报告",
            "target": scan_data.get("target", "N/A"),
            "status": scan_data.get("status", "N/A"),
            "created_at": scan_data.get("created_at", "N/A"),
            "findings": findings,
            "findings_count": len(findings),
            "grouped_findings": grouped_findings,
            "language": config.language,
            "include_raw": config.include_raw,
            "raw_data": scan_data if config.include_raw else None,
        }

    # ==================== HTML 生成 ====================

    def _generate_html(self, scan_data: Dict[str, Any], config: ReportConfig) -> str:
        """生成 HTML 报告（优先使用模板，失败则回退）"""
        template_name = f"{config.template or 'default'}.html.j2"
        try:
            context = self._build_template_context(scan_data, config)
            return self._render_template(template_name, context)
        except (TemplateNotFound, TemplateError) as e:
            logger.warning(f"Template {template_name} failed, using fallback: {e}")
            return self._generate_html_fallback(scan_data, config)

    def _generate_html_fallback(self, scan_data: Dict[str, Any], config: ReportConfig) -> str:
        """
        生成 HTML 报告（内联回退，已修复 XSS 漏洞）
        """
        findings = scan_data.get("findings", [])

        # 分组
        severity_groups: Dict[str, List[Dict]] = {}
        for f in findings:
            severity = f.get("severity", "info")
            if severity not in severity_groups:
                severity_groups[severity] = []
            severity_groups[severity].append(f)

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

        # 构建 HTML 片段（对所有动态数据进行转义）
        findings_html_parts = []
        for severity in sorted_severities:
            items = severity_groups[severity]
            label = html.escape(severity_names.get(severity, severity))
            findings_html_parts.append(f"<h3>{label} ({len(items)})</h3>\n<ul>\n")
            for item in items:
                title = html.escape(item.get("title", "N/A"))
                target = html.escape(item.get("target", "N/A"))
                desc = html.escape(item.get("description", "N/A")[:200])
                findings_html_parts.append(
                    f"""<li><strong>{title}</strong>
<br>目标: {target}
<br>描述: {desc}...</li>\n"""
                )
            findings_html_parts.append("</ul>\n")
        findings_html = "".join(findings_html_parts)

        # 构建完整 HTML
        title = html.escape(config.title or "渗透测试报告")
        target = html.escape(scan_data.get("target", "N/A"))
        status = html.escape(scan_data.get("status", "N/A"))
        created_at = html.escape(scan_data.get("created_at", "N/A"))

        html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - {target}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }}
        h1 {{ color: #333; border-bottom: 3px solid #e74c3c; padding-bottom: 10px; }}
        h2 {{ color: #666; border-bottom: 2px solid #ddd; padding-bottom: 10px; }}
        h3 {{ color: #e74c3c; margin-top: 30px; }}
        ul {{ list-style: none; padding: 0; }}
        li {{ background: #f9f9f9; margin: 10px 0; padding: 15px; border-left: 4px solid #e74c3c; }}
        .summary {{ background: #f0f0f0; padding: 20px; border-radius: 5px; margin-bottom: 30px; }}
        .footer {{ margin-top: 50px; padding-top: 20px; border-top: 1px solid #ddd; color: #999; font-size: 12px; }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    <div class="summary">
        <p><strong>扫描目标:</strong> {target}</p>
        <p><strong>发现数量:</strong> {len(findings)}</p>
        <p><strong>扫描状态:</strong> {status}</p>
        <p><strong>扫描时间:</strong> {created_at}</p>
    </div>
    {findings_html}
    <div class="footer">
        <p>Generated by Pentest Crew Platform</p>
    </div>
</body>
</html>"""
        return html_content

    # ==================== Markdown 生成 ====================

    def _generate_markdown(self, scan_data: Dict[str, Any], config: ReportConfig) -> str:
        """生成 Markdown 报告"""
        template_name = f"{config.template or 'default'}.md.j2"
        try:
            context = self._build_template_context(scan_data, config)
            return self._render_template(template_name, context)
        except (TemplateNotFound, TemplateError) as e:
            logger.warning(f"Template {template_name} failed, using fallback: {e}")
            return self._generate_markdown_fallback(scan_data, config)

    def _generate_markdown_fallback(self, scan_data: Dict[str, Any], config: ReportConfig) -> str:
        """生成 Markdown 报告（内联回退）"""
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
            md += f"## {label} ({len(items)})\n\n"
            for item in items:
                md += f"### {item.get('title', 'N/A')}\n"
                md += f"- **目标**: {item.get('target', 'N/A')}\n"
                md += f"- **描述**: {item.get('description', 'N/A')}\n\n"
                md += "---\n\n"
        return md

    # ==================== PDF 生成 ====================

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

    # ==================== 文件保存与状态更新 ====================

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """清理文件名，防止路径遍历"""
        # 仅允许字母数字、下划线、连字符和点
        if not re.match(r'^[a-zA-Z0-9_.-]+$', filename):
            raise ValueError(f"Invalid filename: {filename}")
        return filename

    def _save_file(self, report_id: str, content: Any, format: ReportFormat) -> str:
        """保存报告文件"""
        ext = format.value
        filename = self._sanitize_filename(f"{report_id}.{ext}")
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