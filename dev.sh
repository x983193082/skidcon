#!/bin/bash
# SkidCon - 开发模式启动脚本
# 同时启动后端和前端开发服务器

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

print_info() {
    echo -e "${CYAN}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 切换到脚本所在目录
cd "$(dirname "$0")"

# 检查虚拟环境
if [ ! -d "venv" ]; then
    print_error "未找到虚拟环境，请先运行: ./setup.sh"
    exit 1
fi

# 激活虚拟环境
source venv/bin/activate

# 检查前端依赖
if [ ! -d "frontend/node_modules" ]; then
    print_warning "前端依赖未安装，正在安装..."
    cd frontend
    npm install
    cd ..
fi

# 显示启动信息
echo ""
print_success "=========================================="
print_success "SkidCon - 开发模式"
print_success "=========================================="
print_info "后端: http://localhost:8000"
print_info "前端: http://localhost:3000"
print_info "按 Ctrl+C 停止所有服务"
print_success "=========================================="
echo ""

# 启动后端（后台）
print_info "启动后端服务器..."
python main.py &
BACKEND_PID=$!

# 等待后端启动
sleep 3

# 启动前端开发服务器
print_info "启动前端开发服务器..."
cd frontend
npm run dev &
FRONTEND_PID=$!

# 等待用户中断
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM

print_info "后端PID: $BACKEND_PID"
print_info "前端PID: $FRONTEND_PID"
print_info "按 Ctrl+C 停止所有服务"

# 等待进程
wait
