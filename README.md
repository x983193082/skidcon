# 🚀 SkidCon - AI 渗透测试系统

基于 CrewAI 的自动化渗透测试平台，集成 50+ Kali 工具，支持多阶段链式攻击和实时输出。

## ✨ 特性

- 🤖 **AI 驱动**: 使用 CrewAI 框架实现多 Agent 协作
- 🔧 **50+ 工具**: 封装 Kali Linux 常用渗透测试工具
- 🔄 **链式攻击**: 支持多阶段自动化攻击流程
- 📊 **实时输出**: WebSocket 推送工具执行进度
- 📝 **自动报告**: 生成详细的 Markdown 格式报告
- ⚡ **并发支持**: 支持至少 3 个任务同时执行
- 🌐 **Web 界面**: Vue 3 构建的现代化单页应用

## 📋 系统要求

- **操作系统**: Kali Linux (推荐)
- **Python**: 3.10+
- **Node.js**: 18+
- **Kali 工具**: 需要安装常用渗透测试工具

## 🚀 快速开始

### 1. 克隆项目

```bash
cd e:\Sec\SkidCon\skidcon-rr
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，填入 OpenRouter API Key
```

### 3. 安装后端依赖

```bash
cd backend
pip install -r requirements.txt
```

### 4. 安装前端依赖

```bash
cd frontend
npm install
```

### 5. 启动服务

**后端** (终端 1):
```bash
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**前端** (终端 2):
```bash
cd frontend
npm run dev
```

### 6. 访问应用

打开浏览器访问: http://localhost:5173

## 📁 项目结构

```
skidcon-rr/
├── backend/                 # 后端代码
│   ├── main.py             # FastAPI 入口
│   ├── config.py           # 配置模块
│   ├── agents.py           # CrewAI Agent 定义
│   ├── tools.py            # Kali 工具封装 (50+)
│   ├── crew_runner.py      # CrewAI 执行核心
│   ├── report.py           # 报告生成模块
│   └── task_manager.py     # 并发任务管理
│
├── frontend/               # 前端代码
│   ├── src/
│   │   ├── App.vue         # 主界面组件
│   │   ├── api.js          # API 请求封装
│   │   └── ws.js           # WebSocket 客户端
│   ├── index.html
│   ├── package.json
│   └── vite.config.js
│
├── data/                   # 数据存储
│   ├── tasks/              # 任务记录 JSON
│   └── reports/            # 生成的报告
│
├── wordlists/              # 字典文件
├── requirements.txt        # Python 依赖
├── .env.example            # 环境变量示例
└── README.md
```

## 🔧 配置说明

### 环境变量 (.env)

```env
OPENROUTER_API_KEY=your_api_key_here    # OpenRouter API Key
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
MODEL_NAME=z-ai/glm-5.1                 # 使用的 AI 模型
MAX_CONCURRENT_TASKS=3                  # 最大并发任务数
TASK_TIMEOUT=1800                       # 任务超时时间 (秒)
```

### 获取 OpenRouter API Key

1. 访问 https://openrouter.ai/
2. 注册账号
3. 在 Dashboard 中创建 API Key
4. 将 Key 填入 `.env` 文件

## 🎯 使用指南

### 1. 创建测试任务

1. 打开 Web 界面
2. 在输入框中输入目标 IP 或 URL
3. 点击"开始测试"按钮

### 2. 查看实时输出

- 左侧面板显示任务进度和阶段状态
- 右侧面板实时显示工具执行输出
- 支持查看历史任务

### 3. 获取测试报告

- 任务完成后自动生成报告
- 支持导出 Markdown 格式
- 报告包含漏洞详情和修复建议

## 🛠️ API 文档

### REST API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/task` | 创建新任务 |
| GET | `/api/task/{id}` | 查询任务状态 |
| GET | `/api/tasks` | 获取所有任务 |
| GET | `/api/report/{id}` | 获取报告内容 |
| GET | `/api/report/{id}/download` | 下载报告文件 |
| GET | `/api/health` | 健康检查 |

### WebSocket

```
/ws/task/{task_id}
```

实时推送任务日志和状态更新。

## 📊 工具列表

### 扫描类
- nmap, masscan, rustscan, naabu

### Web 类
- sqlmap, gobuster, dirb, ffuf, nikto, wpscan, joomscan

### 漏洞利用
- metasploit, searchsploit, nuclei

### 信息收集
- whois, dig, nslookup, theharvester, amass, subfinder, whatweb

### 服务枚举
- enum4linux, smbclient, snmpwalk

### 密码攻击
- hydra, john, hashcat, crunch, cewl

### 后渗透
- linpeas, winpeas, linenum, linux-exploit-suggester

### 其他
- curl, wget, nc, socat

## ⚠️ 免责声明

本工具仅供授权的安全测试使用。未经授权的渗透测试可能违反相关法律法规。

使用者应确保：
1. 已获得目标系统所有者的明确书面授权
2. 遵守相关法律法规和道德准则
3. 不用于非法用途

## 📝 开发说明

### 添加新工具

在 `backend/tools.py` 中添加工具类：

```python
class NewTool(KaliTool):
    def __init__(self):
        super().__init__("newtool", "newtool {target}")
    
    def parse_output(self, stdout, stderr):
        return {"parsed_data": stdout}

# 注册到工具列表
TOOL_REGISTRY["newtool"] = NewTool
```

### 自定义 Agent

在 `backend/agents.py` 中定义新的 Agent：

```python
def create_custom_agent() -> Agent:
    return Agent(
        role="角色名称",
        goal="目标描述",
        backstory="背景故事",
        llm=create_llm(),
        verbose=True
    )
```

## 🐛 常见问题

### Q: 工具执行失败怎么办？

A: 检查以下几点：
1. 确认 Kali 工具已正确安装
2. 检查工具路径配置 (`config.py`)
3. 查看日志输出中的错误信息

### Q: WebSocket 连接断开？

A: 前端会自动重连，如果持续断开请检查：
1. 网络连接是否稳定
2. 后端服务是否正常运行
3. 防火墙设置是否正确

### Q: 报告生成失败？

A: 可能原因：
1. AI API Key 无效或额度不足
2. 任务执行过程中断
3. 检查结果数据是否完整

## 📄 许可证

本项目仅供学习和授权安全测试使用。

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

---

**SkidCon** - 让渗透测试更智能、更高效 🚀
