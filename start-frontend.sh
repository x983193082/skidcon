#!/bin/bash

echo "========================================"
echo "  SkidCon 前端启动脚本"
echo "========================================"
echo ""

echo "[1/2] 检查 Node.js 环境..."
node --version
if [ $? -ne 0 ]; then
    echo "错误: 未找到 Node.js，请先安装 Node.js 18+"
    exit 1
fi

echo ""
echo "[2/2] 安装前端依赖并启动..."
cd frontend
npm install
if [ $? -ne 0 ]; then
    echo "错误: 前端依赖安装失败"
    exit 1
fi

echo ""
echo "前端将运行在 http://localhost:5173"
echo "按 Ctrl+C 停止服务"
echo ""
npm run dev
