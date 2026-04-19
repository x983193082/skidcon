#!/bin/bash
# SkidCon - 首次安装和启动脚本
# 用于在Kali Linux中设置Python虚拟环境并启动项目

set -e  # 遇到错误时退出

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 打印带颜色的消息
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

# 检查是否在Kali Linux中运行
check_kali() {
    if ! command -v apt &> /dev/null; then
        print_warning "未检测到apt包管理器，可能不是Debian/Kali系统"
    fi
    
    if ! command -v python3 &> /dev/null; then
        print_error "未找到Python3，请先安装Python 3.10+"
        exit 1
    fi
    
    PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    print_info "检测到Python版本: $PYTHON_VERSION"
}

# 检查必要的系统依赖
check_dependencies() {
    print_info "检查系统依赖..."
    
    # 检查Python虚拟环境支持
    if ! python3 -m venv --help &> /dev/null; then
        print_warning "未找到venv模块，正在安装..."
        sudo apt-get update
        sudo apt-get install -y python3-venv python3-pip
    fi
    
    # 检查Node.js（前端开发需要）
    if command -v node &> /dev/null; then
        NODE_VERSION=$(node --version)
        print_info "检测到Node.js: $NODE_VERSION"
    else
        print_warning "未检测到Node.js，前端开发需要Node.js 18+"
        print_info "如需构建前端，请运行: sudo apt install -y nodejs npm"
    fi
    
    print_success "系统依赖检查完成"
}

# 创建虚拟环境
setup_venv() {
    VENV_DIR="venv"
    
    if [ -d "$VENV_DIR" ]; then
        print_warning "虚拟环境已存在: $VENV_DIR"
        read -p "是否重新创建？(y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            print_info "删除现有虚拟环境..."
            rm -rf "$VENV_DIR"
        else
            print_info "使用现有虚拟环境"
            return
        fi
    fi
    
    print_info "创建Python虚拟环境..."
    python3 -m venv "$VENV_DIR"
    print_success "虚拟环境创建成功: $VENV_DIR"
}

# 激活虚拟环境并安装依赖
install_dependencies() {
    print_info "激活虚拟环境并安装Python依赖..."
    
    # 激活虚拟环境
    source "$VENV_DIR/bin/activate"
    
    # 升级pip
    print_info "升级pip..."
    pip install --upgrade pip
    
    # 安装依赖
    if [ -f "requirements.txt" ]; then
        print_info "安装requirements.txt中的依赖..."
        pip install -r requirements.txt
        print_success "Python依赖安装完成"
    else
        print_error "未找到requirements.txt文件"
        exit 1
    fi
    
    # 检查是否安装成功
    if python -c "import crewai" &> /dev/null; then
        print_success "CrewAI安装成功"
    else
        print_error "CrewAI安装失败"
        exit 1
    fi
}

# 检查.env文件
check_env_file() {
    if [ ! -f ".env" ]; then
        print_warning "未找到.env配置文件"
        print_info "正在创建.env.example的副本..."
        
        if [ -f ".env.example" ]; then
            cp .env.example .env
            print_warning "请编辑.env文件并填入你的API密钥"
            print_info "运行: nano .env 或 vim .env"
        else
            # 创建默认.env文件
            cat > .env << 'EOF'
# LLM Provider配置
LLM_PROVIDER=openrouter
MODEL_NAME=z-ai/glm-5.1

# OpenRouter API密钥（必填）
OPENROUTER_API_KEY=你的OpenRouter API密钥

# Web服务配置
PORT=8000
LOG_LEVEL=INFO
EOF
            print_warning "已创建默认.env文件，请编辑并填入你的API密钥"
        fi
        
        read -p "是否现在编辑.env文件？(y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            ${EDITOR:-nano} .env
        fi
    else
        print_success "找到.env配置文件"
    fi
}

# 安装前端依赖（可选）
setup_frontend() {
    print_info "是否需要安装前端依赖？（用于前端开发）"
    read -p "安装前端依赖？(y/N): " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        if [ -d "frontend" ] && [ -f "frontend/package.json" ]; then
            if command -v npm &> /dev/null; then
                print_info "安装前端依赖..."
                cd frontend
                npm install
                print_success "前端依赖安装完成"
                cd ..
            else
                print_error "未找到npm，请先安装Node.js"
            fi
        else
            print_warning "未找到frontend目录或package.json"
        fi
    else
        print_info "跳过前端依赖安装"
        print_info "如需构建前端，请运行: cd frontend && npm install && npm run build"
    fi
}

# 构建前端（可选）
build_frontend() {
    print_info "是否需要构建前端？（用于生产环境）"
    read -p "构建前端？(y/N): " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        if [ -d "frontend" ] && [ -f "frontend/package.json" ]; then
            if command -v npm &> /dev/null; then
                print_info "构建前端..."
                cd frontend
                npm run build
                print_success "前端构建完成，输出到 web/static/"
                cd ..
            else
                print_error "未找到npm"
            fi
        else
            print_warning "未找到frontend目录"
        fi
    else
        print_info "跳过前端构建"
    fi
}

# 启动应用
start_application() {
    print_info "启动SkidCon应用..."
    print_info "激活虚拟环境..."
    source "$VENV_DIR/bin/activate"
    
    print_success "=========================================="
    print_success "SkidCon - AI渗透测试助手"
    print_success "=========================================="
    print_info "Web界面: http://localhost:${PORT:-8000}"
    print_info "按 Ctrl+C 停止应用"
    print_success "=========================================="
    echo
    
    # 启动应用
    python main.py
}

# 显示使用帮助
show_help() {
    echo "用法: $0 [选项]"
    echo ""
    echo "选项:"
    echo "  --install-only    仅安装，不启动应用"
    echo "  --no-frontend     跳过前端相关步骤"
    echo "  --port PORT       指定Web服务端口（默认8000）"
    echo "  --help            显示此帮助信息"
    echo ""
    echo "示例:"
    echo "  $0                  # 完整安装并启动"
    echo "  $0 --install-only   # 仅安装依赖"
    echo "  $0 --port 9000      # 使用9000端口启动"
    echo ""
}

# 主函数
main() {
    echo ""
    print_success "=========================================="
    print_success "SkidCon - 安装和启动脚本"
    print_success "=========================================="
    echo ""
    
    # 解析命令行参数
    INSTALL_ONLY=false
    NO_FRONTEND=false
    PORT=8000
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --install-only)
                INSTALL_ONLY=true
                shift
                ;;
            --no-frontend)
                NO_FRONTEND=true
                shift
                ;;
            --port)
                PORT="$2"
                shift 2
                ;;
            --help)
                show_help
                exit 0
                ;;
            *)
                print_error "未知参数: $1"
                show_help
                exit 1
                ;;
        esac
    done
    
    # 切换到脚本所在目录
    cd "$(dirname "$0")"
    
    # 执行安装步骤
    check_kali
    check_dependencies
    setup_venv
    install_dependencies
    check_env_file
    
    if [ "$NO_FRONTEND" = false ]; then
        setup_frontend
        build_frontend
    fi
    
    if [ "$INSTALL_ONLY" = true ]; then
        print_success "=========================================="
        print_success "安装完成！"
        print_success "=========================================="
        print_info "运行以下命令启动应用:"
        echo ""
        echo "  source venv/bin/activate"
        echo "  python main.py"
        echo ""
        print_info "或使用快速启动脚本:"
        echo ""
        echo "  ./run.sh"
        echo ""
        exit 0
    fi
    
    # 启动应用
    start_application
}

# 运行主函数
main "$@"
