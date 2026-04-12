"""
Scan Routes - 扫描相关API路由
"""

from fastapi import APIRouter, HTTPException
from typing import List
from pydantic import BaseModel, Field
from datetime import datetime
from loguru import logger

from ...core.scan_manager import get_scan_manager, ScanStatus as ManagerScanStatus
from ..models.schemas import ScanResponse, ScanProgress, ScanResultsResponse


router = APIRouter()


class ScanStartRequest(BaseModel):
    """启动扫描请求"""

    target: str = Field(..., description="目标地址")
    scope: List[str] = Field(default_factory=list, description="测试范围")
    scan_type: str = Field(default="full", description="扫描类型")
    options: dict = Field(default_factory=dict, description="扫描选项")


class OperationResponse(BaseModel):
    """操作响应"""

    success: bool
    message: str


@router.post("/start", response_model=ScanResponse)
async def start_scan(request: ScanStartRequest):
    """启动新的扫描任务"""
    try:
        scan_manager = get_scan_manager()
        scan_id = scan_manager.create_scan(
            target=request.target,
            scope=request.scope,
            scan_type=request.scan_type,
            options=request.options,
        )

        return ScanResponse(
            scan_id=scan_id,
            status=ManagerScanStatus.PENDING.value,
            message="Scan created successfully",
            created_at=datetime.now().isoformat(),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create scan: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{scan_id}", response_model=ScanProgress)
async def get_scan_status(scan_id: str):
    """获取扫描状态"""
    scan_manager = get_scan_manager()
    scan_data = scan_manager.get_status(scan_id)

    if not scan_data:
        raise HTTPException(status_code=404, detail="Scan not found")

    findings_key = scan_manager._get_findings_key(scan_id)
    findings_count = scan_manager.client.llen(findings_key)

    started_at = None
    if scan_data.get("started_at"):
        started_at = datetime.fromisoformat(scan_data["started_at"]).isoformat()

    return ScanProgress(
        scan_id=scan_id,
        status=scan_data.get("status", "pending"),
        progress=scan_data.get("progress", 0),
        current_phase=scan_data.get("current_phase", ""),
        findings_count=findings_count,
        started_at=started_at,
    )


@router.post("/{scan_id}/pause", response_model=OperationResponse)
async def pause_scan(scan_id: str):
    """暂停扫描"""
    scan_manager = get_scan_manager()
    success = scan_manager.pause(scan_id)

    if not success:
        scan_data = scan_manager.get_status(scan_id)
        if not scan_data:
            raise HTTPException(status_code=404, detail="Scan not found")
        raise HTTPException(
            status_code=400,
            detail=f"Cannot pause scan in status: {scan_data['status']}",
        )

    return OperationResponse(success=True, message="Scan paused successfully")


@router.post("/{scan_id}/resume", response_model=OperationResponse)
async def resume_scan(scan_id: str):
    """恢复扫描"""
    scan_manager = get_scan_manager()
    success = scan_manager.resume(scan_id)

    if not success:
        scan_data = scan_manager.get_status(scan_id)
        if not scan_data:
            raise HTTPException(status_code=404, detail="Scan not found")
        raise HTTPException(
            status_code=400,
            detail=f"Cannot resume scan in status: {scan_data['status']}",
        )

    return OperationResponse(success=True, message="Scan resumed successfully")


@router.post("/{scan_id}/stop", response_model=OperationResponse)
async def stop_scan(scan_id: str):
    """停止扫描"""
    scan_manager = get_scan_manager()
    success = scan_manager.stop(scan_id)

    if not success:
        scan_data = scan_manager.get_status(scan_id)
        if not scan_data:
            raise HTTPException(status_code=404, detail="Scan not found")
        raise HTTPException(
            status_code=400, detail=f"Cannot stop scan in status: {scan_data['status']}"
        )

    return OperationResponse(success=True, message="Scan stopped successfully")


@router.get("/{scan_id}/results", response_model=ScanResultsResponse)
async def get_scan_results(scan_id: str):
    """获取扫描结果"""
    scan_manager = get_scan_manager()
    results = scan_manager.get_results(scan_id)

    if not results:
        raise HTTPException(status_code=404, detail="Scan not found")

    return results


@router.get("/stats")
async def get_scan_stats():
    """获取扫描统计"""
    scan_manager = get_scan_manager()
    return scan_manager.get_stats()
