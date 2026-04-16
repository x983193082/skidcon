@echo off
echo ========================================
echo   SkidCon - AI 渗透测试系统
echo ========================================
echo.

echo [1/3] 检查 Python 环境...
python --version
if errorlevel 1 (
    echo 错误: 未找到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

echo.
echo [2/3] 安装后端依赖...
cd backend
pip install -r requirements.txt
if errorlevel 1 (
    echo 错误: 后端依赖安装失败
    pause
    exit /b 1
)

echo.
echo [3/3] 启动后端服务...
echo 后端将运行在 http://localhost:8000
echo 按 Ctrl+C 停止服务
echo.
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
