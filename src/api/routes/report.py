"""
Report Routes - 报告相关API路由
"""
import os
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field
from loguru import logger

from ...core.report_generator import (
    get_report_generator,
    ReportFormat as GeneratorReportFormat,
    ReportConfig,
)
from ...core.scan_manager import get_scan_manager
from ..models.schemas import ReportInfo


router = APIRouter()


class ReportRequest(BaseModel):
    """报告生成请求"""
    scan_id: str = Field(..., description="扫描任务ID")
    format: str = Field(default="pdf", description="报告格式")
    include_raw: bool = Field(default=False, description="是否包含原始数据")
    language: str = Field(default="zh-CN", description="报告语言")


class ReportResponse(BaseModel):
    """报告创建响应"""
    report_id: str
    scan_id: str
    status: str
    message: str


class OperationResponse(BaseModel):
    """操作响应"""
    success: bool
    message: str


# 格式映射
FORMAT_MAP = {
    "pdf": GeneratorReportFormat.PDF,
    "html": GeneratorReportFormat.HTML,
    "json": GeneratorReportFormat.JSON,
    "markdown": GeneratorReportFormat.MARKDOWN,
}

# MIME类型映射
MIME_TYPES = {
    "pdf": "application/pdf",
    "html": "text/html",
    "json": "application/json",
    "markdown": "text/markdown",
}


def _safe_file_response(file_path: str, output_dir: str, report_id: str, format: str) -> FileResponse:
    """
    安全返回文件响应，校验路径是否在允许的目录内
    """
    real_file = os.path.realpath(file_path)
    real_dir = os.path.realpath(output_dir)
    if not real_file.startswith(real_dir):
        logger.warning(f"Attempt to access file outside output directory: {file_path}")
        raise HTTPException(status_code=403, detail="Access denied")

    ext = format if format in MIME_TYPES else "pdf"
    media_type = MIME_TYPES.get(ext, "application/octet-stream")
    filename = f"report_{report_id}.{ext}"
    return FileResponse(file_path, media_type=media_type, filename=filename)


@router.post("/generate", response_model=ReportResponse)
async def generate_report(request: ReportRequest):
    """
    生成渗透测试报告

    注意：当前为同步生成，大报告可能耗时较长，
    建议后续改为异步任务模式。
    """
    try:
        # 验证 scan_id 存在
        scan_manager = get_scan_manager()
        scan_data = scan_manager.get_status(request.scan_id)
        if not scan_data:
            raise HTTPException(status_code=404, detail="Scan not found")

        # 转换格式
        format_key = request.format.lower()
        if format_key not in FORMAT_MAP:
            raise HTTPException(status_code=400, detail=f"Unsupported format: {request.format}")
        report_format = FORMAT_MAP[format_key]

        # 使用核心模块的 ReportConfig
        config = ReportConfig(
            scan_id=request.scan_id,
            format=report_format,
            language=request.language,
            include_raw=request.include_raw,
            title="",
        )

        # 同步生成报告（TODO: 改为队列异步）
        report_generator = get_report_generator()
        report_id = report_generator.generate(request.scan_id, config)

        return ReportResponse(
            report_id=report_id,
            scan_id=request.scan_id,
            status="completed",
            message="Report generated successfully",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to generate report: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{report_id}", response_model=ReportInfo)
async def get_report(report_id: str):
    """获取报告信息"""
    report_generator = get_report_generator()
    report_data = report_generator.get_report(report_id)

    if not report_data:
        raise HTTPException(status_code=404, detail="Report not found")

    created_at = datetime.fromisoformat(report_data["created_at"]) if report_data.get("created_at") else datetime.now()

    return ReportInfo(
        report_id=report_data.get("report_id", ""),
        scan_id=report_data.get("scan_id", ""),
        title=report_data.get("title") or f"Report for {report_data.get('scan_id', '')}",
        format=report_data.get("format", "pdf"),
        status=report_data.get("status", "generating"),
        created_at=created_at,
    )


@router.get("/{report_id}/download")
async def download_report(report_id: str, format: Optional[str] = None):
    """
    下载报告文件

    - **format**: 指定下载格式，必须与报告实际格式一致（可选，用于校验）
    """
    report_generator = get_report_generator()
    report_data = report_generator.get_report(report_id)

    if not report_data:
        raise HTTPException(status_code=404, detail="Report not found")

    if report_data.get("status") != "completed":
        raise HTTPException(status_code=400, detail="Report not ready for download")

    actual_format = report_data.get("format")
    if format and format.lower() != actual_format:
        raise HTTPException(status_code=400, detail=f"Report format is {actual_format}, requested {format}")

    file_path = report_data.get("file_path")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Report file not found")

    return _safe_file_response(
        file_path=file_path,
        output_dir=report_generator.output_dir,
        report_id=report_id,
        format=actual_format,
    )


@router.get("/{report_id}/preview")
async def preview_report(report_id: str):
    """
    预览报告（HTML格式）

    如果报告是HTML格式且已生成，直接返回文件内容；
    否则动态生成HTML预览（不保存文件）。
    """
    report_generator = get_report_generator()
    report_data = report_generator.get_report(report_id)

    if not report_data:
        raise HTTPException(status_code=404, detail="Report not found")

    # 若报告为HTML且已完成，直接返回文件
    if report_data.get("format") == "html" and report_data.get("status") == "completed":
        file_path = report_data.get("file_path")
        if file_path and os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            return HTMLResponse(content=content, media_type="text/html")

    # 否则动态生成预览
    scan_id = report_data.get("scan_id")
    if not scan_id:
        raise HTTPException(status_code=400, detail="Invalid report data")

    scan_manager = get_scan_manager()
    scan_results = scan_manager.get_results(scan_id)

    if not scan_results:
        raise HTTPException(status_code=404, detail="Scan data not found")

    # 构建预览配置
    config = ReportConfig(
        scan_id=scan_id,
        format=GeneratorReportFormat.HTML,
        language=report_data.get("language", "zh-CN"),
        include_raw=report_data.get("include_raw", False),
        title=report_data.get("title", ""),
    )

    # 临时方案：直接调用内部生成方法（后续应封装为公共预览方法）
    html_content = report_generator._generate_html(scan_results, config)

    return HTMLResponse(content=html_content, media_type="text/html")