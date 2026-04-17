# 使用示例

## 快速开始

1. **配置环境变量**

创建 `.env` 文件：
```env
OPENROUTER_API_KEY=你的OpenRouter API密钥
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
MODEL_NAME=z-ai/glm-5.1
PORT=8000
LOG_LEVEL=INFO
```

2. **安装依赖**

```bash
pip install -r requirements.txt
```

3. **运行程序**

```bash
python main.py
```

程序启动后会自动开启Web界面，访问 **http://localhost:8000** 即可查看对话历史。

## 使用示例

### 示例1: 端口扫描
```
> 扫描192.168.1.1的开放端口
```

系统会自动：
1. Level 1 Agent 识别为 "scanning" 任务
2. Level 2 Agent (Scanning Expert) 选择 nmap 工具并执行

### 示例2: Web漏洞扫描
```
> 对http://example.com进行SQL注入测试
```

系统会自动：
1. Level 1 Agent 识别为 "web_exploitation" 任务
2. Level 2 Agent (Web Exploitation Expert) 选择 sqlmap 工具并执行

### 示例3: 信息收集
```
> 收集example.com的子域名信息
```

系统会自动：
1. Level 1 Agent 识别为 "information_collection" 任务
2. Level 2 Agent (Information Collection Expert) 选择 amass 或 theharvester 工具并执行

### 示例4: 自定义代码执行
```
> 写一段Python代码来扫描192.168.1.1的80端口
```

或

```
> 帮我执行Python代码，读取/etc/passwd文件
```

系统会自动：
1. Level 1 Agent 识别为 "custom_code" 任务
2. Level 2 Agent (Custom Code Executor) 直接执行Python代码
3. 代码在Kali Linux环境中运行，返回执行结果

### 示例5: 密码破解
```
> 使用hashcat破解这个hash: 5f4dcc3b5aa765d61d8327deb882cf99
```

系统会自动：
1. Level 1 Agent 识别为 "password_crypto" 任务
2. Level 2 Agent (Password & Crypto Expert) 选择 hashcat 工具并执行

## 工作流程

```
用户输入任务
    ↓
Level 1 Agent (任务分类) → 判断是工具任务还是闲聊
    ↓                    ↓
    ↓               Chat Agent (直接回答)
    ↓
Level 2 Agent (选择工具并执行)
    ↓
Kali Linux 直接执行命令
    ↓
返回结果
```

## 架构说明

- **执行环境**: 直接在 Kali Linux 环境中执行命令（不使用Docker）
- **AI框架**: CrewAI 0.86.0
- **LLM**: OpenRouter API
- **前端**: Vue 3 + Vite (开发模式 http://localhost:3000)
- **后端**: FastAPI + Uvicorn (http://localhost:8000)

## 注意事项

- 所有命令直接在 Kali Linux 环境中执行，确保环境中有相应的渗透测试工具
- API调用需要有效的 OpenRouter API 密钥
- 执行结果会实时显示在终端和Web界面中
- 确保运行环境为 Kali Linux 或已安装所需安全工具的 Linux 系统

