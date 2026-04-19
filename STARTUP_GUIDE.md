# SkidCon 启动脚本说明

本文档说明如何在Kali Linux中使用启动脚本。

## 脚本说明

项目提供三个启动脚本，适用于不同场景：

| 脚本 | 用途 | 使用场景 |
|------|------|----------|
| `setup.sh` | 首次安装和启动 | 新环境初始化 |
| `run.sh` | 快速启动 | 日常使用 |
| `dev.sh` | 开发模式 | 前端开发 |

## 快速开始

### 首次安装

```bash
# 1. 克隆项目（如果还没有）
git clone <repository-url>
cd skidcon

# 2. 添加执行权限
chmod +x setup.sh run.sh dev.sh

# 3. 运行安装脚本
./setup.sh
```

安装脚本会自动完成以下步骤：
1. ✅ 检查Python版本（需要3.10+）
2. ✅ 检查系统依赖
3. ✅ 创建Python虚拟环境（venv）
4. ✅ 安装requirements.txt中的依赖
5. ✅ 检查并创建.env配置文件
6. ✅ 可选安装前端依赖
7. ✅ 可选构建前端
8. ✅ 启动应用

### 日常启动

```bash
# 使用快速启动脚本
./run.sh
```

快速启动脚本会：
1. 检查虚拟环境是否存在
2. 激活虚拟环境
3. 启动应用

### 开发模式

```bash
# 同时启动后端和前端开发服务器
./dev.sh
```

开发模式会：
1. 启动后端服务器（端口8000）
2. 启动前端开发服务器（端口3000）
3. 前端自动代理后端API请求

## 命令行参数

### setup.sh 参数

```bash
# 仅安装依赖，不启动应用
./setup.sh --install-only

# 跳过前端相关步骤
./setup.sh --no-frontend

# 指定Web服务端口
./setup.sh --port 9000

# 显示帮助
./setup.sh --help
```

### 示例

```bash
# 完整安装并启动（默认端口8000）
./setup.sh

# 仅安装依赖，稍后手动启动
./setup.sh --install-only

# 安装并指定端口
./setup.sh --port 9000

# 安装时跳过前端
./setup.sh --no-frontend
```

## 手动启动

如果不想使用脚本，也可以手动启动：

```bash
# 1. 激活虚拟环境
source venv/bin/activate

# 2. 启动应用
python main.py
```

## 环境要求

### 系统要求

- **操作系统**: Kali Linux（推荐）或Debian系Linux
- **Python**: 3.10+
- **Node.js**: 18+（仅前端开发需要）

### 必要工具

```bash
# 安装Python和venv
sudo apt update
sudo apt install -y python3 python3-venv python3-pip

# 安装Node.js（可选，前端开发需要）
sudo apt install -y nodejs npm
```

## 虚拟环境说明

### 虚拟环境位置

```
skidcon/
├── venv/              # Python虚拟环境
│   ├── bin/           # 可执行文件
│   ├── lib/           # Python包
│   └── ...
├── setup.sh           # 安装脚本
├── run.sh             # 启动脚本
└── dev.sh             # 开发模式脚本
```

### 激活虚拟环境

```bash
# Bash/Zsh
source venv/bin/activate

# 检查是否激活
which python
# 应该输出: /path/to/skidcon/venv/bin/python

python --version
# 应该显示Python版本
```

### 退出虚拟环境

```bash
deactivate
```

### 在虚拟环境中安装包

```bash
# 激活虚拟环境
source venv/bin/activate

# 安装新包
pip install package-name

# 更新requirements.txt
pip freeze > requirements.txt
```

## 配置文件

### .env 文件

安装脚本会自动检查并创建.env文件。必要配置：

```env
# LLM Provider配置
LLM_PROVIDER=openrouter
MODEL_NAME=z-ai/glm-5.1

# API密钥（必填）
OPENROUTER_API_KEY=你的API密钥

# Web服务配置
PORT=8000
LOG_LEVEL=INFO
```

### 编辑.env文件

```bash
# 使用nano编辑
nano .env

# 或使用vim
vim .env
```

## 前端构建

### 开发模式

```bash
cd frontend
npm run dev
```

前端开发服务器运行在 http://localhost:3000

### 生产构建

```bash
cd frontend
npm run build
```

构建产物输出到 `web/static/` 目录

### 预览构建产物

```bash
cd frontend
npm run preview
```

## 故障排除

### 问题1: 权限错误

```bash
# 添加执行权限
chmod +x setup.sh run.sh dev.sh
```

### 问题2: 虚拟环境创建失败

```bash
# 安装venv模块
sudo apt install -y python3-venv

# 删除现有虚拟环境
rm -rf venv

# 重新运行安装脚本
./setup.sh
```

### 问题3: 依赖安装失败

```bash
# 激活虚拟环境
source venv/bin/activate

# 升级pip
pip install --upgrade pip

# 重新安装依赖
pip install -r requirements.txt
```

### 问题4: 端口被占用

```bash
# 使用其他端口启动
./setup.sh --port 9000

# 或修改.env文件
PORT=9000
```

### 问题5: 前端无法访问

```bash
# 检查前端是否构建
ls -la web/static/

# 如果不存在，构建前端
cd frontend
npm run build
cd ..

# 或使用开发模式
./dev.sh
```

## 停止应用

```bash
# 按 Ctrl+C 停止

# 或查找并杀死进程
ps aux | grep main.py
kill <PID>
```

## 更新项目

```bash
# 1. 拉取最新代码
git pull

# 2. 激活虚拟环境
source venv/bin/activate

# 3. 更新依赖
pip install -r requirements.txt

# 4. 更新前端依赖（如果需要）
cd frontend
npm install
cd ..

# 5. 重新启动
./run.sh
```

## 生产部署

### 使用systemd服务

创建服务文件 `/etc/systemd/system/skidcon.service`:

```ini
[Unit]
Description=SkidCon AI Penetration Testing Assistant
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/skidcon
ExecStart=/path/to/skidcon/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl start skidcon
sudo systemctl enable skidcon
sudo systemctl status skidcon
```

### 使用Docker（可选）

如果需要容器化部署，可以参考Dockerfile配置。

## 安全注意事项

⚠️ **重要提醒**:

1. 本工具仅用于授权的安全测试环境
2. 确保获得合法的测试授权
3. 遵守当地法律法规
4. 建议在隔离环境中使用
5. 不要在生产环境中直接运行此工具
