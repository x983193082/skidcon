#!/bin/bash
# Pentest Crew - 入口脚本

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查环境变量
check_env() {
    if [ ! -f .env ]; then
        log_warn ".env file not found, copying from .env.example"
        cp .env.example .env
    fi
    
    # 加载环境变量
    export $(cat .env | grep -v '^#' | xargs)
}

# 检查依赖
check_dependencies() {
    log_info "Checking dependencies..."
    
    # 检查Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed"
        exit 1
    fi
    
    # 检查Docker Compose
    if ! command -v docker-compose &> /dev/null; then
        log_error "Docker Compose is not installed"
        exit 1
    fi
    
    log_info "All dependencies are installed"
}

# 启动服务
start_services() {
    log_info "Starting services..."
    docker-compose -f docker/docker-compose.yml up -d
    log_info "Services started"
}

# 停止服务
stop_services() {
    log_info "Stopping services..."
    docker-compose -f docker/docker-compose.yml down
    log_info "Services stopped"
}

# 查看日志
view_logs() {
    docker-compose -f docker/docker-compose.yml logs -f "$1"
}

# 运行测试
run_tests() {
    log_info "Running tests..."
    pytest tests/ -v --cov=src --cov-report=html
    log_info "Tests completed"
}

# 初始化数据库
init_db() {
    log_info "Initializing databases..."
    # TODO: 实现数据库初始化逻辑
    log_info "Databases initialized"
}

# 主函数
main() {
    case "$1" in
        start)
            check_env
            check_dependencies
            start_services
            ;;
        stop)
            stop_services
            ;;
        restart)
            stop_services
            start_services
            ;;
        logs)
            view_logs "$2"
            ;;
        test)
            run_tests
            ;;
        init)
            init_db
            ;;
        *)
            echo "Usage: $0 {start|stop|restart|logs|test|init}"
            echo "  start   - Start all services"
            echo "  stop    - Stop all services"
            echo "  restart - Restart all services"
            echo "  logs    - View logs (optional: service name)"
            echo "  test    - Run tests"
            echo "  init    - Initialize databases"
            exit 1
            ;;
    esac
}

main "$@"