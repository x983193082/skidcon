"""
Prompt Routes - Prompt 管理 API
"""

from fastapi import APIRouter, HTTPException
from typing import Optional
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/prompts", tags=["Prompts"])


class PromptUpdateRequest(BaseModel):
    key: str
    value: str


class VersionCreateRequest(BaseModel):
    version: str
    changelog: str


class VersionSwitchRequest(BaseModel):
    version: str


@router.get("/")
async def get_all_prompts():
    """获取所有可用的 prompt"""
    try:
        from config.prompts.loader import get_prompt_loader

        loader = get_prompt_loader()
        return {"agents": loader.get_all_agents()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load agents: {str(e)}")


@router.get("/{agent_type}")
async def get_prompt(agent_type: str):
    """获取指定 Agent 的 prompt"""
    try:
        from config.prompts.manager import get_prompt_manager

        pm = get_prompt_manager()
        return {
            "agent_type": agent_type,
            "role": pm.get_role(agent_type),
            "goal": pm.get_goal(agent_type),
            "backstory": pm.get_backstory(agent_type),
            "tasks": pm.get_tasks(agent_type),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get prompt: {str(e)}")


@router.put("/{agent_type}")
async def update_prompt(agent_type: str, request: PromptUpdateRequest):
    """更新 prompt（运行时）"""
    try:
        from config.prompts.manager import get_prompt_manager

        pm = get_prompt_manager()
        success = pm.update_prompt(agent_type, request.key, request.value)
        if success:
            return {"success": True, "message": f"Updated {agent_type}.{request.key}"}
        raise HTTPException(
            status_code=400,
            detail=f"Failed to update prompt. Key '{request.key}' may not be allowed.",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@router.delete("/{agent_type}")
async def reset_agent_prompt(agent_type: str):
    """重置指定 Agent 的所有 prompt"""
    try:
        from config.prompts.manager import get_prompt_manager

        pm = get_prompt_manager()
        success = pm.reset_all(agent_type)
        if success:
            return {"success": True, "message": f"Reset all prompts for {agent_type}"}
        raise HTTPException(status_code=500, detail="Failed to reset prompts")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@router.get("/versions/")
async def get_versions():
    """获取版本列表"""
    try:
        from config.prompts.versions import get_version_manager

        vm = get_version_manager()
        return vm.get_version_info()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get versions: {str(e)}")


@router.get("/versions/{version}")
async def get_version_detail(version: str):
    """获取指定版本详情"""
    try:
        from config.prompts.versions import get_version_manager

        vm = get_version_manager()
        info = vm.get_version_info(version)
        if info:
            return {
                "version": info.version,
                "created_at": info.created_at,
                "changelog": info.changelog,
                "active": info.active,
            }
        raise HTTPException(status_code=404, detail=f"Version {version} not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@router.put("/versions/")
async def switch_version_legacy(version: str):
    """切换版本（旧版接口，兼容前端）"""
    try:
        from config.prompts.versions import get_version_manager

        vm = get_version_manager()
        success = vm.switch_version(version)
        if success:
            return {"success": True, "message": f"Switched to version {version}"}
        raise HTTPException(status_code=404, detail=f"Version {version} not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@router.put("/versions/switch")
async def switch_version(request: VersionSwitchRequest):
    """切换版本（新版接口，符合 RESTful）"""
    try:
        from config.prompts.versions import get_version_manager

        vm = get_version_manager()
        success = vm.switch_version(request.version)
        if success:
            return {
                "success": True,
                "message": f"Switched to version {request.version}",
            }
        raise HTTPException(
            status_code=404, detail=f"Version {request.version} not found"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@router.post("/versions/")
async def create_version(request: VersionCreateRequest):
    """创建新版本"""
    try:
        from config.prompts.versions import get_version_manager

        vm = get_version_manager()
        success = vm.create_version(request.version, request.changelog)
        if success:
            return {"success": True, "message": f"Created version {request.version}"}
        raise HTTPException(
            status_code=400,
            detail=f"Version {request.version} already exists or invalid",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")
