#!/bin/bash

echo "========================================"
echo "  SkidCon 前端启动脚本"
echo "========================================"
echo ""

echo "[1/3] 检查 Node.js 环境..."
if ! command -v node &> /dev/null; then
    echo "错误: 未找到 Node.js，请先安装 Node.js 18+"
    echo "运行: curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -"
    echo "      sudo apt install -y nodejs"
    exit 1
fi

NODE_VERSION=$(node --version | cut -d'v' -f2 | cut -d'.' -f1)
if [ "$NODE_VERSION" -lt 18 ]; then
    echo "错误: Node.js 版本过低 (当前: $(node --version))，需要 18+"
    exit 1
fi

echo "Node.js 版本: $(node --version) ✅"

echo ""
echo "[2/3] 安装前端依赖..."
cd frontend
if [ ! -d "node_modules" ]; then
    echo "首次安装依赖，请稍候..."
    npm install
    if [ $? -ne 0 ]; then
        echo "错误: 前端依赖安装失败"
        exit 1
    fi
else
    echo "依赖已存在，检查更新..."
    npm install
fi

echo ""
echo "[3/3] 启动前端开发服务器..."
echo "前端将运行在 http://0.0.0.0:5173"
echo "按 Ctrl+C 停止服务"
echo ""
npm run dev -- --host
