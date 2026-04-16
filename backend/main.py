"""
SkidCon FastAPI 主应用
提供 REST API 和 WebSocket 接口
"""

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from typing import Optional
import os

from config import REPORTS_DIR
from task_manager import task_manager, TaskStatus
from crew_runner import run_pentest
from report import report_generator


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时加载历史任务
    task_manager.load_tasks_from_disk()
    print("✅ SkidCon 启动成功!")
    print(f"📊 已加载 {len(task_manager.tasks)} 个历史任务")
    yield
    # 关闭时清理资源
    print("👋 SkidCon 已关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title="SkidCon - AI 渗透测试系统",
    description="基于 CrewAI 的自动化渗透测试平台",
    version="1.0.0",
    lifespan=lifespan
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== 数据模型 ====================

class CreateTaskRequest(BaseModel):
    target: str


class TaskResponse(BaseModel):
    id: str
    target: str
    status: str
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


# ==================== 启动事件 ====================
# (已迁移到 lifespan 函数)


# ==================== REST API ====================

@app.post("/api/task", response_model=TaskResponse)
async def create_task(request: CreateTaskRequest):
    """创建新的渗透测试任务"""
    task = task_manager.create_task(target=request.target)
    
    # 异步执行任务
    asyncio.create_task(
        task_manager.execute_task(
            task=task,
            executor_func=run_pentest
        )
    )
    
    return TaskResponse(
        id=task.id,
        target=task.target,
        status=task.status,
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at
    )


@app.get("/api/task/{task_id}")
async def get_task(task_id: str):
    """获取任务详情"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    return task.to_dict()


@app.get("/api/tasks")
async def get_tasks():
    """获取所有任务列表"""
    return task_manager.get_all_tasks()


@app.get("/api/report/{task_id}")
async def get_report(task_id: str):
    """获取任务报告"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    if task.status != TaskStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="任务尚未完成")
    
    report_content = report_generator.get_report(task_id)
    if not report_content:
        # 如果报告不存在，尝试生成
        if task.result:
            report_path = report_generator.generate_report(
                task_id=task_id,
                target=task.target,
                results=task.result
            )
            with open(report_path, "r", encoding="utf-8") as f:
                report_content = f.read()
        else:
            raise HTTPException(status_code=404, detail="报告不存在")
    
    return {"content": report_content}


@app.get("/api/report/{task_id}/download")
async def download_report(task_id: str):
    """下载报告文件"""
    report_path = REPORTS_DIR / f"{task_id}.md"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="报告文件不存在")
    
    return FileResponse(
        path=str(report_path),
        filename=f"skidcon_report_{task_id}.md",
        media_type="text/markdown"
    )


@app.get("/api/reports")
async def list_reports():
    """列出所有报告"""
    return report_generator.list_reports()


@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {
        "status": "ok",
        "version": "1.0.0",
        "max_concurrent_tasks": task_manager.max_concurrent,
        "active_tasks": sum(1 for t in task_manager.tasks.values() if t.status == TaskStatus.RUNNING)
    }


# ==================== WebSocket ====================

@app.websocket("/ws/task/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    """WebSocket 端点，实时推送任务日志"""
    task = task_manager.get_task(task_id)
    if not task:
        await websocket.close(code=4004, reason="任务不存在")
        return
    
    await websocket.accept()
    
    # 注册 WebSocket 客户端
    task_manager.register_websocket(task_id, websocket)
    
    try:
        # 发送历史日志
        for log in task.logs:
            await websocket.send_json({
                "type": "log",
                "task_id": task_id,
                "message": log
            })
        
        # 发送当前状态
        await websocket.send_json({
            "type": "status",
            "task_id": task_id,
            "status": task.status
        })
        
        # 保持连接，等待新消息
        while True:
            # 接收客户端消息（保持心跳）
            data = await websocket.receive_text()
            
            # 可以处理客户端发来的命令
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    
    except WebSocketDisconnect:
        print(f"WebSocket 客户端断开: {task_id}")
    except Exception as e:
        print(f"WebSocket 错误: {e}")
    finally:
        # 注销 WebSocket 客户端
        task_manager.unregister_websocket(task_id, websocket)


# ==================== 主入口 ====================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
