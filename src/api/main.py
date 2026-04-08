"""
FastAPI Main Entry - API服务入口
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Optional
import uvicorn

from .routes import scan, task, report
from .models import schemas


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # Startup
    print("Starting Pentest Crew API...")
    yield
    # Shutdown
    print("Shutting down Pentest Crew API...")


app = FastAPI(
    title="Pentest Crew API",
    description="渗透测试自动化平台API",
    version="1.0.0",
    lifespan=lifespan
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境需要限制
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(scan.router, prefix="/api/v1/scan", tags=["Scan"])
app.include_router(task.router, prefix="/api/v1/task", tags=["Task"])
app.include_router(report.router, prefix="/api/v1/report", tags=["Report"])


@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "Pentest Crew API",
        "version": "1.0.0",
        "docs": "/docs"
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy"}


def run_server(host: str = "0.0.0.0", port: int = 8000):
    """启动API服务器"""
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()