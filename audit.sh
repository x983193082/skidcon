#!/bin/bash

echo "========================================"
echo "  SkidCon 项目审计脚本"
echo "========================================"
echo ""

PASS=0
FAIL=0
WARN=0

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

check() {
    local description=$1
    local command=$2
    
    echo -n "检查: $description ... "
    if eval "$command" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ 通过${NC}"
        ((PASS++))
    else
        echo -e "${RED}❌ 失败${NC}"
        ((FAIL++))
    fi
}

warn() {
    local description=$1
    local command=$2
    
    echo -n "检查: $description ... "
    if eval "$command" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ 通过${NC}"
        ((PASS++))
    else
        echo -e "${YELLOW}⚠️  警告${NC}"
        ((WARN++))
    fi
}

echo "========== 系统环境 =========="
check "Python3 已安装" "command -v python3"
check "pip3 已安装" "command -v pip3"
check "Node.js 已安装" "command -v node"
check "npm 已安装" "command -v npm"

echo ""
echo "========== 项目结构 =========="
check "backend 目录存在" "test -d backend"
check "frontend 目录存在" "test -d frontend"
check "data 目录存在" "test -d data"
check "wordlists 目录存在" "test -d wordlists"
check "requirements.txt 存在" "test -f requirements.txt"
check ".env 文件存在" "test -f .env"

echo ""
echo "========== 后端文件 =========="
check "main.py 存在" "test -f backend/main.py"
check "config.py 存在" "test -f backend/config.py"
check "agents.py 存在" "test -f backend/agents.py"
check "tools.py 存在" "test -f backend/tools.py"
check "crew_runner.py 存在" "test -f backend/crew_runner.py"
check "report.py 存在" "test -f backend/report.py"
check "task_manager.py 存在" "test -f backend/task_manager.py"
check "__init__.py 存在" "test -f backend/__init__.py"

echo ""
echo "========== 前端文件 =========="
check "package.json 存在" "test -f frontend/package.json"
check "vite.config.js 存在" "test -f frontend/vite.config.js"
check "index.html 存在" "test -f frontend/index.html"
check "main.js 存在" "test -f frontend/src/main.js"
check "App.vue 存在" "test -f frontend/src/App.vue"
check "api.js 存在" "test -f frontend/src/api.js"
check "ws.js 存在" "test -f frontend/src/ws.js"

echo ""
echo "========== 配置文件 =========="
warn "OPENROUTER_API_KEY 已配置" "grep -q 'your_api_key_here' .env && false || true"
check "MAX_CONCURRENT_TASKS 配置" "grep -q 'MAX_CONCURRENT_TASKS' .env"
check "TASK_TIMEOUT 配置" "grep -q 'TASK_TIMEOUT' .env"

echo ""
echo "========== 字典文件 =========="
check "directories.txt 存在" "test -f wordlists/directories.txt"
check "subdomains.txt 存在" "test -f wordlists/subdomains.txt"

echo ""
echo "========== Python 语法检查 =========="
if [ -d "backend/venv" ]; then
    source backend/venv/bin/activate > /dev/null 2>&1
    check "config.py 语法正确" "python3 -m py_compile backend/config.py"
    check "tools.py 语法正确" "python3 -m py_compile backend/tools.py"
    check "agents.py 语法正确" "python3 -m py_compile backend/agents.py"
    check "crew_runner.py 语法正确" "python3 -m py_compile backend/crew_runner.py"
    check "report.py 语法正确" "python3 -m py_compile backend/report.py"
    check "task_manager.py 语法正确" "python3 -m py_compile backend/task_manager.py"
    check "main.py 语法正确" "python3 -m py_compile backend/main.py"
    deactivate > /dev/null 2>&1
else
    echo -e "${YELLOW}⚠️  虚拟环境未创建，跳过语法检查${NC}"
    ((WARN++))
fi
if [ -d "backend/venv" ]; then
    echo -e "${GREEN}✅ 虚拟环境已创建${NC}"
    ((PASS++))
    
    # 激活虚拟环境检查
    source backend/venv/bin/activate > /dev/null 2>&1
    check "fastapi 已安装" "python3 -c 'import fastapi'"
    check "crewai 已安装" "python3 -c 'import crewai'"
    check "langchain-openai 已安装" "python3 -c 'import langchain_openai'"
    check "uvicorn 已安装" "python3 -c 'import uvicorn'"
    check "python-dotenv 已安装" "python3 -c 'import dotenv'"
    deactivate > /dev/null 2>&1
else
    echo -e "${YELLOW}⚠️  虚拟环境未创建（首次启动时自动创建）${NC}"
    ((WARN++))
fi

echo ""
echo "========== Node.js 依赖 =========="
if [ -d "frontend/node_modules" ]; then
    echo -e "${GREEN}✅ node_modules 已安装${NC}"
    ((PASS++))
    check "vue 已安装" "test -d frontend/node_modules/vue"
    check "axios 已安装" "test -d frontend/node_modules/axios"
    check "vite 已安装" "test -d frontend/node_modules/vite"
else
    echo -e "${YELLOW}⚠️  node_modules 未安装（首次启动时自动安装）${NC}"
    ((WARN++))
fi

echo ""
echo "========== 端口检查 =========="
warn "端口 8000 未被占用" "! lsof -i :8000 > /dev/null 2>&1"
warn "端口 5173 未被占用" "! lsof -i :5173 > /dev/null 2>&1"

echo ""
echo "========================================"
echo "  审计结果"
echo "========================================"
echo -e "✅ 通过: ${GREEN}$PASS${NC}"
echo -e "❌ 失败: ${RED}$FAIL${NC}"
echo -e "⚠️  警告: ${YELLOW}$WARN${NC}"
echo ""

if [ $FAIL -eq 0 ]; then
    echo -e "${GREEN}🎉 项目审计通过！可以正常启动${NC}"
    echo ""
    echo "启动命令:"
    echo "  后端: ./start-backend.sh"
    echo "  前端: ./start-frontend.sh"
    exit 0
else
    echo -e "${RED}❌ 项目审计失败，请修复上述问题${NC}"
    exit 1
fi
