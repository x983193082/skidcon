#!/bin/bash

echo "========================================"
echo "  SkidCon - AI 渗透测试系统"
echo "========================================"
echo ""

echo "[1/4] 检查 Python 环境..."
python3 --version
if [ $? -ne 0 ]; then
    echo "错误: 未找到 Python3，请先安装 Python 3.10+"
    echo "运行: sudo apt install python3 python3-venv python3-pip"
    exit 1
fi

echo ""
echo "[2/4] 创建 Python 虚拟环境..."
cd backend
if [ ! -d "venv" ]; then
    echo "创建虚拟环境..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "错误: 虚拟环境创建失败"
        echo "运行: sudo apt install python3-venv"
        exit 1
    fi
else
    echo "虚拟环境已存在，跳过创建"
fi

echo ""
echo "[3/4] 激活虚拟环境并安装依赖..."
source venv/bin/activate
pip install --upgrade pip
pip install -r ../requirements.txt
if [ $? -ne 0 ]; then
    echo "错误: 依赖安装失败"
    echo "尝试: sudo apt install python3-dev build-essential"
    exit 1
fi

echo ""
echo "[4/4] 启动后端服务..."
echo "后端将运行在 http://0.0.0.0:8000"
echo "按 Ctrl+C 停止服务"
echo ""
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
