#!/bin/bash
# SkidCon - 快速启动脚本
# 用于在已安装的环境中快速启动应用

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

# 检查虚拟环境是否存在
if [ ! -d "venv" ]; then
    print_error "未找到虚拟环境，请先运行安装脚本"
    print_info "运行: ./setup.sh"
    exit 1
fi

# 检查.env文件
if [ ! -f ".env" ]; then
    print_error "未找到.env配置文件"
    print_info "请运行: ./setup.sh 或手动创建.env文件"
    exit 1
fi

# 激活虚拟环境
print_info "激活虚拟环境..."
source venv/bin/activate

# 检查关键依赖
if ! python -c "import crewai" &> /dev/null; then
    print_error "CrewAI未安装，请重新运行安装脚本"
    print_info "运行: ./setup.sh"
    exit 1
fi

# 显示启动信息
echo ""
print_success "=========================================="
print_success "SkidCon - AI渗透测试助手"
print_success "=========================================="
print_info "Python环境: $(python --version)"
print_info "虚拟环境: $(which python)"
print_info "Web界面: http://localhost:${PORT:-8000}"
print_info "按 Ctrl+C 停止应用"
print_success "=========================================="
echo ""

# 启动应用
python main.py
