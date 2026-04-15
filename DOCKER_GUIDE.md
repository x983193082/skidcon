# Pentest Crew - Docker 完整运行指南

## 📋 前提条件

- Docker 20.10+
- Docker Compose 2.0+
- 至少 4GB 可用内存
- 至少 10GB 可用磁盘空间

## 🚀 快速启动

### 1. 配置环境变量

```bash
# 在项目根目录执行
cp .env.example .env

# 编辑 .env 文件，至少配置以下变量：
# OPENROUTER_API_KEY=your_api_key_here  # 或 OPENAI_API_KEY
# LLM_PROVIDER=openrouter              # 或 openai
```

### 2. 构建并启动所有服务

```bash
cd docker

# 启动核心服务（API + Worker + Redis + ChromaDB）
docker-compose up -d

# 查看服务状态
docker-compose ps

# 查看日志
docker-compose logs -f api
```

### 3. 验证服务

```bash
# 检查 API 健康状态
curl http://localhost:8000/health

# 访问 API 文档
# 浏览器打开: http://localhost:8000/docs
```

## 🔧 服务说明

| 服务 | 端口 | 说明 |
|------|------|------|
| api | 8000 | FastAPI 主服务 |
| worker | - | 后台任务处理 |
| redis | 6379 | 任务队列 |
| chroma | 8001 | 向量数据库 |
| qdrant | 6333, 6334 | 向量数据库（可选） |
| neo4j | 7474, 7687 | 图数据库（可选） |

## 📦 可选服务

### 启动 Qdrant（替代 ChromaDB）

```bash
docker-compose --profile qdrant up -d
```

### 启动 Neo4j（攻击图存储）

```bash
docker-compose --profile graph up -d
```

### 启动所有服务

```bash
docker-compose --profile qdrant --profile graph up -d
```

## 🔍 常用命令

```bash
# 查看日志
docker-compose logs -f api        # API 日志
docker-compose logs -f worker     # Worker 日志
docker-compose logs -f redis      # Redis 日志

# 重启服务
docker-compose restart api
docker-compose restart worker

# 停止所有服务
docker-compose down

# 停止并删除数据卷（⚠️ 会丢失所有数据）
docker-compose down -v

# 重新构建镜像
docker-compose up -d --build

# 进入容器调试
docker exec -it pentest-crew-api bash
docker exec -it pentest-crew-worker bash
```

## 📊 数据持久化

以下数据通过 Docker Volume 持久化：

| 数据卷 | 存储内容 |
|--------|----------|
| redis-data | Redis 任务队列数据 |
| chroma-data | ChromaDB 向量数据 |
| qdrant-data | Qdrant 向量数据 |
| neo4j-data | Neo4j 图数据 |
| api-data | SQLite 数据库文件 |
| worker-data | Worker 数据库文件 |

## ⚠️ 注意事项

### 1. Windows 环境

在 Windows 上使用 Docker Desktop 时：

```powershell
# 确保 Docker Desktop 正在运行
docker info

# 如果遇到路径问题，使用绝对路径
docker-compose -f "E:\Sec\SkidCon\skidcon-refactorMinerva\docker\docker-compose.yml" up -d
```

### 2. 安全工具限制

Docker 容器内预装了以下工具：
- ✅ nmap（网络扫描）
- ✅ sqlmap（Worker 容器）
- ❌ metasploit（需要额外配置）

如需使用 Metasploit，需要：
1. 安装 Metasploit 主机版
2. 配置 `METASPLOIT_RPC_HOST` 指向宿主机 IP
3. 在 Docker 中使用 `host.docker.internal` 访问宿主机

### 3. 网络扫描限制

容器内扫描宿主机网络时：

```bash
# 使用宿主机 IP（Docker Desktop）
# Windows/Mac: host.docker.internal
# Linux: 172.17.0.1

# 示例：扫描宿主机
curl -X POST http://localhost:8000/api/v1/scan/start \
  -H "Content-Type: application/json" \
  -d '{"target": "host.docker.internal", "scan_type": "quick"}'
```

### 4. 性能优化

如果内存不足，可以：

```bash
# 只启动核心服务
docker-compose up -d api redis chroma

# 限制容器资源
# 在 docker-compose.yml 中添加：
# deploy:
#   resources:
#     limits:
#       memory: 2G
#       cpus: '2.0'
```

## 🐛 故障排查

### API 无法启动

```bash
# 查看详细日志
docker-compose logs api

# 常见问题：
# 1. 缺少 API Key - 检查 .env 文件
# 2. Redis 未启动 - docker-compose up -d redis
# 3. 端口冲突 - 修改 docker-compose.yml 中的端口映射
```

### Worker 无法连接 Redis

```bash
# 检查 Redis 是否运行
docker-compose ps redis

# 检查网络连接
docker exec pentest-crew-worker ping redis
```

### 向量数据库连接失败

```bash
# 检查 ChromaDB 状态
docker-compose ps chroma

# 查看 ChromaDB 日志
docker-compose logs chroma
```

## 📝 完整启动示例

```bash
# 1. 进入项目目录
cd E:\Sec\SkidCon\skidcon-refactorMinerva

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 API Key

# 3. 启动所有服务
cd docker
docker-compose up -d

# 4. 等待服务启动（约 30 秒）
docker-compose ps

# 5. 验证服务
curl http://localhost:8000/health

# 6. 访问 API 文档
# 浏览器: http://localhost:8000/docs
```

## 🎯 测试渗透扫描

```bash
# 创建扫描任务
curl -X POST http://localhost:8000/api/v1/scan/start \
  -H "Content-Type: application/json" \
  -d '{
    "target": "testphp.vulnweb.com",
    "scope": ["testphp.vulnweb.com"],
    "scan_type": "quick"
  }'

# 查看扫描状态
curl http://localhost:8000/api/v1/scan/{scan_id}

# 查看扫描结果
curl http://localhost:8000/api/v1/scan/{scan_id}/results
```

## 📊 资源占用

| 服务 | CPU | 内存 | 磁盘 |
|------|-----|------|------|
| API | ~10% | ~500MB | ~100MB |
| Worker | ~5% | ~300MB | ~50MB |
| Redis | ~2% | ~50MB | ~10MB |
| ChromaDB | ~15% | ~400MB | ~200MB |
| **总计** | **~32%** | **~1.25GB** | **~360MB** |

---

**总结**: 项目可以完整在 Docker 中运行，只需配置 `.env` 文件中的 API Key 即可开始使用！
