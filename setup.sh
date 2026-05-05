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

# 安装Playwright CLI和浏览器（交互式可选）
install_playwright_cli() {
    echo ""
    print_info "=========================================="
    print_info "  Playwright CLI (浏览器自动化工具)"
    print_info "=========================================="
    print_info "SkidCon 的浏览器测试功能需要 Playwright CLI。"
    echo ""
    
    # 检查是否已安装
    if command -v playwright-cli &> /dev/null; then
        print_success "Playwright CLI 已安装: $(playwright-cli --version 2>/dev/null || echo '未知')"
        
        # 检查浏览器是否已安装
        print_info "检查已安装的浏览器..."
        BROWSER_STATUS=""
        for browser in chromium firefox webkit; do
            if playwright-cli install --dry-run "$browser" &>/dev/null; then
                BROWSER_STATUS="$BROWSER_STATUS  ✅ $browser 已安装"
            else
                BROWSER_STATUS="$BROWSER_STATUS  ❌ $browser 未安装"
            fi
        done
        echo "$BROWSER_STATUS"
        echo ""
        print_info "如需重新安装浏览器，运行: ./setup.sh --browser"
        return 0
    fi
    
    print_warning "未安装 Playwright CLI"
    print_info "安装需要下载浏览器文件："
    print_info "  [1] 仅 Chromium (推荐，约 400MB) - 覆盖 95% 测试场景"
    print_info "  [2] Chromium + Firefox (约 600MB) - 支持跨浏览器测试"
    print_info "  [3] 全部安装 (约 950MB) - Chromium + Firefox + WebKit"
    print_info "  [4] 跳过 - 稍后手动安装"
    echo ""
    read -p "请选择 [1-4] (默认1): " -n 1 -r BROWSER_CHOICE
    echo ""
    
    case "${BROWSER_CHOICE:-1}" in
        1)
            BROWSERS="chromium"
            ;;
        2)
            BROWSERS="chromium firefox"
            ;;
        3)
            BROWSERS="chromium firefox webkit"
            ;;
        4)
            print_warning "跳过 Playwright CLI 安装"
            print_info "浏览器测试功能将不可用"
            print_info "稍后可手动安装: ./setup.sh --browser"
            return 0
            ;;
        *)
            print_warning "无效选择，默认安装 Chromium"
            BROWSERS="chromium"
            ;;
    esac
    
    # 检查Node.js
    if ! command -v node &> /dev/null; then
        print_info "安装 Node.js..."
        sudo apt-get update -qq
        sudo apt-get install -y nodejs npm
    fi
    
    NODE_VERSION=$(node -v 2>/dev/null | sed 's/v//' | cut -d. -f1)
    if [ -n "$NODE_VERSION" ] && [ "$NODE_VERSION" -lt 18 ] 2>/dev/null; then
        print_warning "Node.js 版本过低 (当前v$(node -v)，需要 18+)，正在升级..."
        curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
        sudo apt-get install -y nodejs
    fi
    print_success "Node.js: $(node -v)"
    
    # 安装 Playwright CLI
    print_info "安装 Playwright CLI..."
    sudo npm install -g @playwright/cli@latest
    
    if ! command -v playwright-cli &> /dev/null; then
        print_error "Playwright CLI 安装失败"
        print_info "请手动运行: sudo npm install -g @playwright/cli@latest"
        return 1
    fi
    print_success "Playwright CLI 安装完成"
    
    # 安装浏览器和系统依赖
    print_info "安装浏览器及系统依赖..."
    print_info "正在安装: $BROWSERS"
    sudo playwright-cli install --with-deps $BROWSERS
    
    # 验证安装
    if command -v playwright-cli &> /dev/null; then
        print_success "Playwright CLI 安装完成！"
        print_info "验证: playwright-cli open https://example.com"
    else
        print_error "Playwright CLI 安装验证失败"
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
    echo "  --no-browser      跳过 Playwright CLI 安装"
    echo "  --browser         单独安装 Playwright CLI 和浏览器"
    echo "  --port PORT       指定Web服务端口（默认8000）"
    echo "  --help            显示此帮助信息"
    echo ""
    echo "示例:"
    echo "  $0                  # 完整安装并启动"
    echo "  $0 --install-only   # 仅安装依赖"
    echo "  $0 --no-browser     # 安装但跳过浏览器"
    echo "  $0 --browser        # 单独安装浏览器工具"
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
    NO_BROWSER=false
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
            --no-browser)
                NO_BROWSER=true
                shift
                ;;
            --browser)
                cd "$(dirname "$0")"
                install_playwright_cli
                exit 0
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
    
    if [ "$NO_BROWSER" = false ]; then
        install_playwright_cli
    else
        print_info "跳过 Playwright CLI 安装 (--no-browser)"
        print_info "稍后可运行: ./setup.sh --browser"
    fi
    
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
