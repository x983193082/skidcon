# Kali Linux 运行可行性审计报告

> 审计日期：2026-04-15
> 审计目标：评估项目在 Kali Linux 上直接运行的可行性

---

## 📊 总体评估：✅ 高度可行

项目在 Kali Linux 上直接运行**完全可行**，且比 Docker 方案更简单高效。

---

## 🔍 组件依赖分析

### 1. 安全工具依赖

| 工具 | Docker 方案 | Kali 自带 | 需要修改 |
|------|-------------|-----------|----------|
| **nmap** | 容器内安装 | ✅ `/usr/bin/nmap` | ❌ 无需修改 |
| **sqlmap** | 容器内安装 | ✅ `/usr/bin/sqlmap` | ❌ 无需修改 |
| **metasploit** | 需 RPC 配置 | ✅ `/usr/bin/msfconsole` | ⚠️ 需启动 msfrpcd |
| **python3** | 容器内 | ✅ 系统自带 | ❌ 无需修改 |

**结论**：Kali 自带所有核心安全工具，工具路径配置完全兼容。

---

### 2. 基础设施依赖

| 组件 | Docker 方案 | Kali 方案 | 安装难度 |
|------|-------------|-----------|----------|
| **Redis** | Docker 容器 | `sudo apt install redis-server` | ⭐ 简单 |
| **ChromaDB** | Docker 容器 | `pip install chromadb` | ⭐ 简单 |
| **SQLite** | 文件存储 | 文件存储 | ❌ 无需修改 |
| **Neo4j** | 可选 Docker | `sudo apt install neo4j` | ⭐⭐ 中等 |
| **Qdrant** | 可选 Docker | 二进制下载 | ⭐⭐ 中等 |

**结论**：核心依赖（Redis + ChromaDB）安装简单，Neo4j/Qdrant 为可选组件。

---

### 3. Python 依赖

| 类别 | 包名 | Kali 兼容性 | 备注 |
|------|------|-------------|------|
| **CrewAI** | crewai, crewai-tools | ✅ | 核心框架 |
| **Web** | fastapi, uvicorn | ✅ | API 服务 |
| **向量库** | chromadb, qdrant-client | ✅ | 知识库 |
| **LLM** | litellm, langchain | ✅ | AI 模型 |
| **数据库** | sqlalchemy, aiosqlite | ✅ | 数据存储 |
| **工具** | redis, docker, httpx | ✅ | 基础设施 |
| **报告** | jinja2, weasyprint | ⚠️ | weasyprint 需系统依赖 |

**结论**：所有 Python 包在 Kali 上均可正常安装。

---

## ⚠️ 需要修改的配置

### 1. `.env` 配置调整

```env
# ====== 必须修改 ======

# Redis 连接（从容器名改为 localhost）
REDIS_URL=redis://localhost:6379/0

# 数据库路径（从容器路径改为本地路径）
DATABASE_URL=sqlite:///./data/skidcon.db

# 向量数据库（从容器 URL 改为本地路径）
VECTOR_DB_TYPE=chroma
VECTOR_DB_URL=http://localhost:8000  # 如果启动 Chroma 服务

# 工具路径（Kali 默认路径，通常无需修改）
NMAP_PATH=/usr/bin/nmap
SQLMAP_PATH=/usr/bin/sqlmap

# ====== 建议修改 ======

# 禁用 Docker 沙箱（Kali 上不需要）
DOCKER_SANDBOX_ENABLED=false

# 日志配置（可选）
LOG_LEVEL=INFO
LOG_FILE=./logs/pentest.log

# 报告输出目录
REPORT_OUTPUT_DIR=./reports
```

---

### 2. `settings.py` 默认值调整

**当前问题**：
```python
# src/core/settings.py
database_url: str = "sqlite:////app/data/skidcon.db"  # ❌ 容器路径
nmap_path: str = "/usr/bin/nmap"                      # ✅ Kali 兼容
sqlmap_path: str = "/usr/bin/sqlmap"                  # ✅ Kali 兼容
```

**建议修改**：
```python
database_url: str = "sqlite:///./data/skidcon.db"  # ✅ 相对路径
```

---

### 3. Docker 沙箱功能

**当前代码**：`src/utils/docker_sandbox.py`

在 Kali 上运行时，Docker 沙箱功能可以：
- **保留**：如果需要在隔离环境中执行危险操作
- **禁用**：如果信任工具执行环境

**建议**：通过环境变量控制：
```env
DOCKER_SANDBOX_ENABLED=false
```

---

### 4. WeasyPrint 系统依赖

**问题**：生成 PDF 报告需要 `weasyprint`，它依赖系统库。

**安装命令**：
```bash
sudo apt install -y \
    python3-pip python3-cffi python3-brotli \
    libpango-1.0-0 libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 libffi-dev \
    shared-mime-info
```

---

## 🚀 Kali 部署步骤

### 快速启动（推荐）

```bash
# 1. 安装系统依赖
sudo apt update
sudo apt install -y redis-server python3-pip python3-venv

# 2. 启动 Redis
sudo systemctl start redis-server
sudo systemctl enable redis-server

# 3. 创建虚拟环境（推荐）
python3 -m venv venv
source venv/bin/activate

# 4. 安装 Python 依赖
pip install -r requirements.txt

# 5. 创建必要目录
mkdir -p data reports logs

# 6. 配置 .env 文件
cp .env.example .env
# 编辑 .env，修改 REDIS_URL 和 DATABASE_URL

# 7. 启动 API 服务（终端 1）
python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload

# 8. 启动 Worker（终端 2）
python -m src.worker.main
```

### 可选：启动 ChromaDB 服务

如果需要独立的 ChromaDB 服务（非嵌入式）：

```bash
pip install chromadb
chroma run --host 0.0.0.0 --port 8000 --path ./data/chroma
```

---

## 🔧 代码修改清单

### 必须修改（2 处）

| 文件 | 修改内容 | 原因 |
|------|----------|------|
| `src/core/settings.py` | `database_url` 默认值 | 容器路径在 Kali 上不存在 |
| `.env` | `REDIS_URL`, `DATABASE_URL` | 连接本地服务而非容器 |

### 建议修改（3 处）

| 文件 | 修改内容 | 原因 |
|------|----------|------|
| `src/core/settings.py` | `docker_sandbox_enabled` 默认值 | Kali 上通常不需要沙箱 |
| `src/worker/task_executor.py` | 添加 `_execute_full_scan` | 修复任务类型不匹配问题 |
| `requirements.txt` | 添加注释说明可选依赖 | 区分核心/可选依赖 |

### 可选修改（2 处）

| 文件 | 修改内容 | 原因 |
|------|----------|------|
| `src/tools/msf_wrapper.py` | 添加命令行模式支持 | 默认使用 RPC，Kali 上可直接用 msfconsole |
| `src/utils/docker_sandbox.py` | 添加本地执行回退 | 禁用 Docker 时使用本地执行 |

---

## 📋 兼容性检查清单

| 检查项 | 状态 | 备注 |
|--------|------|------|
| Python 3.11+ | ✅ | Kali 2024+ 自带 Python 3.11+ |
| Redis 连接 | ✅ | localhost:6379 |
| nmap 调用 | ✅ | subprocess 调用，PATH 中存在即可 |
| sqlmap 调用 | ✅ | subprocess 调用，PATH 中存在即可 |
| Metasploit | ⚠️ | 需要启动 msfrpcd 或改用命令行模式 |
| ChromaDB | ✅ | 支持嵌入式模式，无需独立服务 |
| SQLite | ✅ | 文件存储，无兼容问题 |
| CrewAI | ✅ | 纯 Python 包，无系统依赖 |
| FastAPI | ✅ | 纯 Python 包，无系统依赖 |
| PDF 生成 | ⚠️ | 需要安装 weasyprint 系统依赖 |

---

## 🎯 优势对比

| 维度 | Docker 方案 | Kali 直接运行 |
|------|-------------|---------------|
| **部署复杂度** | ⭐⭐⭐ 高 | ⭐ 低 |
| **工具更新** | 需重建镜像 | `sudo apt update` |
| **调试便利性** | 需进入容器 | 直接调试 |
| **性能** | 容器开销 | 原生性能 |
| **工具数量** | 需手动安装 | 600+ 自带工具 |
| **网络配置** | 需配置桥接 | 直接访问 |
| **权限管理** | 需映射 Docker socket | 直接使用 sudo |

---

## 💡 建议

### 推荐方案：Kali 直接运行

**适用场景**：
- 个人渗透测试
- 开发调试
- CTF/靶场练习
- 红队演练

**优势**：
1. 工具齐全，无需额外安装
2. 部署简单，5 分钟启动
3. 调试方便，直接查看日志
4. 性能更好，无容器开销

### 保留 Docker 方案的场景

- 生产环境部署
- 非 Kali 系统（Windows/macOS）
- 需要隔离执行环境
- 团队协作/CI/CD

---

## 📝 总结

项目在 Kali Linux 上运行**完全可行**，只需修改 2 处配置即可。

**核心修改**：
1. `.env` 中的 `REDIS_URL` 和 `DATABASE_URL`
2. `settings.py` 中的 `database_url` 默认值

**可选优化**：
1. 禁用 Docker 沙箱
2. 安装 weasyprint 系统依赖（PDF 报告）
3. 启动 msfrpcd（Metasploit RPC）

**预计部署时间**：10-15 分钟

---

*审计完成，项目架构设计良好，工具封装规范，迁移到 Kali 几乎没有障碍。*
