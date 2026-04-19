# SkidCon - AI渗透测试助手

一个基于 **CrewAI** 三层Agent架构的智能渗透测试系统，直接在 **Kali Linux** 环境中执行安全测试工具。

## 📋 目录

- [架构说明](#架构说明)
- [功能特性](#功能特性)
- [技术栈](#技术栈)
- [项目结构](#项目结构)
- [安装](#安装)
- [使用方法](#使用方法)
- [工作流程](#工作流程)
- [Agent架构](#agent架构)
- [支持的工具](#支持的工具)
- [Web API](#web-api)
- [配置说明](#配置说明)
- [安全注意事项](#安全注意事项)

## 架构说明

本项目采用创新的**三层Agent架构**，结合智能记忆管理和决策引擎，实现自动化的渗透测试流程：

### 核心架构层次

1. **Level 1 Agent (任务分类器)**: 
   - 将用户任务分类到不同的安全测试领域
   - 支持闲聊模式(chat)和工具调用模式(handoff)
   - 基于JSON格式的结构化决策输出

2. **Level 2 Agent (领域专家)**: 
   - 12个专业领域的专家Agent
   - 每个领域配备专门的工具集和执行策略
   - 覆盖信息收集、扫描、枚举、Web利用、漏洞利用等全渗透测试流程

3. **Level 3 Agent (工具执行器)**: 
   - 直接在Kali Linux环境中执行命令
   - 支持50+渗透测试工具
   - 安全的命令执行机制（防注入）

### 辅助系统

- **Memory Manager**: 智能记忆管理，支持滑动窗口、重要性评估、总结机制
- **Decision Engine**: 渗透测试决策引擎，自动规划测试阶段
- **Result Verifier**: 结果验证器，验证工具执行结果的有效性
- **Report Generator**: 报告生成器，生成JSON/Markdown格式渗透测试报告
- **Test State**: 结构化测试状态管理，跟踪发现的主机、服务、漏洞等

## 功能特性

- ✅ **三层Agent自动路由和执行** - 智能任务分类和工具选择
- ✅ **支持50+渗透测试工具** - nmap, sqlmap, metasploit, hashcat等
- ✅ **直接在Kali Linux环境中执行** - 无需Docker，原生执行
- ✅ **流式输出** - 实时查看执行过程和Agent思考
- ✅ **多领域安全测试** - 信息收集、扫描、枚举、Web利用、漏洞利用、密码破解、无线攻击等
- ✅ **智能记忆管理** - 避免上下文超出token限制
- ✅ **结果验证** - 自动验证工具执行结果
- ✅ **报告生成** - 自动生成结构化渗透测试报告
- ✅ **PoC技能库** - 内置CVE漏洞利用技能（Log4Shell等）
- ✅ **现代化Web界面** - Vue3+Vite前端，实时对话展示
- ✅ **多LLM支持** - OpenRouter API，支持多种模型（GLM-5.1、GPT-4等）
- ✅ **多Provider支持** - OpenRouter、OpenAI、DeepSeek、SiliconFlow等

## 技术栈

| 类别 | 技术 |
|------|------|
| **AI框架** | CrewAI 0.86.0 |
| **LLM** | OpenRouter API (默认: z-ai/glm-5.1) |
| **后端** | FastAPI + Uvicorn |
| **前端** | Vue 3 + Vite + Axios |
| **执行环境** | Kali Linux (直接执行) |
| **记忆管理** | tiktoken (token计数) |
| **命令行** | subprocess (安全执行) |

## 项目结构

```
skidcon/
├── main.py                      # 主入口程序
├── requirements.txt             # Python依赖
├── .env                         # 环境变量配置（需创建）
├── config/                      # 配置模块
│   ├── execute_config.py        # LLM配置（多Provider支持）
│   ├── tool_category_mapping.py # 工具到类别的映射
│   └── tools_manuals.py         # 工具手册和描述
├── core/                        # 核心模块
│   ├── agent_runner.py          # Agent运行器（三级Agent调度）
│   ├── level1_agent.py          # Level 1: 任务分类Agent
│   ├── level2_agent.py          # Level 2: 12个领域专家Agent
│   ├── chat_agent.py            # 闲聊Agent
│   ├── kali_executor.py         # Kali命令执行器
│   ├── tools.py                 # CrewAI工具定义
│   ├── memory_manager.py        # 智能记忆管理
│   ├── decision_engine.py       # 渗透测试决策引擎
│   ├── result_verifier.py       # 结果验证器
│   ├── report_generator.py      # 报告生成器
│   ├── test_state.py            # 测试状态管理
│   └── planning_agent.py        # 渗透测试规划器
├── web/                         # Web后端
│   ├── app.py                   # FastAPI应用
│   └── static/                  # 前端构建产物
├── frontend/                    # Web前端
│   ├── src/
│   │   ├── App.vue              # Vue主组件
│   │   └── main.js              # 入口文件
│   ├── index.html               # HTML模板
│   ├── package.json             # 前端依赖
│   └── vite.config.js           # Vite配置
└── skills/                      # PoC技能库
    └── pocs/                    # CVE漏洞利用技能
        ├── navigation.md        # 技能导航
        ├── apache_log4j/        # Log4Shell CVE-2021-44228
        ├── apache_http_server/  # Apache HTTP Server CVE-2021-42013
        └── ...                  # 更多CVE技能
```

## 安装

### 1. 环境要求

- **Python**: 3.10+
- **操作系统**: Kali Linux（虚拟机或物理机）
- **Node.js**: 18+ (用于前端开发)
- **网络**: 需要访问LLM API（OpenRouter等）

### 2. 安装Python依赖

```bash
cd SkidCon
pip install -r requirements.txt
```

### 3. 配置环境变量

创建 `.env` 文件（参考 `.env.example`）：

```env
# LLM Provider配置
LLM_PROVIDER=openrouter          # 支持的provider: openrouter, openai, deepseek, siliconflow, custom
MODEL_NAME=z-ai/glm-5.1          # 模型名称

# OpenRouter配置（默认）
OPENROUTER_API_KEY=你的OpenRouter API密钥
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1

# 其他Provider配置（可选）
# OPENAI_API_KEY=你的OpenAI API密钥
# DEEPSEEK_API_KEY=你的DeepSeek API密钥
# SILICONFLOW_API_KEY=你的SiliconFlow API密钥

# 自定义Provider配置（当LLM_PROVIDER=custom时使用）
# CUSTOM_API_KEY=你的API密钥
# CUSTOM_BASE_URL=https://your-api-endpoint/v1

# Web服务配置
PORT=8000                        # Web服务端口
LOG_LEVEL=INFO                   # 日志级别
```

### 4. 安装前端依赖（可选，仅开发时需要）

```bash
cd frontend
npm install
```

## 使用方法

### 运行主程序

```bash
python main.py
```

程序启动后会自动开启Web界面，访问 **http://localhost:8000** 即可在浏览器中查看对话历史。

### 前端开发模式

```bash
cd frontend
npm run dev
```

前端开发服务器运行在 http://localhost:3000，会自动代理后端API请求。

### 构建前端

```bash
cd frontend
npm run build
```

构建后的文件会输出到 `web/static` 目录。

### 命令行交互

程序启动后，可以在终端直接输入任务：

```
> 扫描192.168.1.1的开放端口
> 对http://example.com进行SQL注入测试
> 使用hashcat破解密码哈希
```

支持的命令：
- `quit` / `exit` / `q`: 退出程序
- `clear` / `清空`: 清空对话历史
- `history` / `历史` / `h`: 查看对话历史摘要

## 工作流程

```
用户输入任务
    ↓
┌─────────────────────────────────┐
│  Level 1 Agent (任务分类)        │
│  - 分析任务类型                  │
│  - 输出JSON决策                  │
│  - action: handoff 或 chat       │
└─────────────────────────────────┘
    ↓
    ├─ action=chat ─→ Chat Agent (直接回答)
    │
    └─ action=handoff ─→ 根据target分类
                         ↓
                    ┌─────────────────────────────────┐
                    │  Level 2 Agent (领域专家)        │
                    │  - 选择合适工具                  │
                    │  - 生成执行命令                  │
                    │  - 调用kali_command工具          │
                    └─────────────────────────────────┘
                         ↓
                    ┌─────────────────────────────────┐
                    │  Kali Executor (命令执行)        │
                    │  - 安全执行命令                  │
                    │  - 捕获stdout/stderr             │
                    │  - 超时处理                      │
                    └─────────────────────────────────┘
                         ↓
                    返回执行结果
```

## Agent架构

### Level 1: 任务分类器

**职责**: 将用户输入分类到正确的安全测试领域

**输出格式**:
```json
{
  "action": "handoff",
  "target": "scanning"
}
```

**支持的target**:
- `information_collection`: 信息收集
- `scanning`: 网络扫描
- `enumeration`: 服务枚举
- `web_exploitation`: Web漏洞利用
- `exploitation`: 漏洞利用
- `password_crypto`: 密码破解
- `wireless_attack`: 无线攻击
- `reverse_engineering`: 逆向工程
- `forensics`: 取证分析
- `post_exploitation`: 后渗透
- `custom_code`: 自定义代码执行

### Level 2: 领域专家 (12个Agent)

| Agent | 领域 | 主要工具 |
|-------|------|----------|
| `agent_information_collection` | 信息收集与OSINT | amass, theharvester, recon-ng, spiderfoot, fierce, dnsenum |
| `agent_scanning` | 网络扫描 | nmap, masscan, tcpdump, tshark, httpx, gobuster |
| `agent_enumeration` | 服务枚举 | enum4linux, dirb, ffuf, wfuzz, nikto, wpscan, gobuster |
| `agent_web_exploitation` | Web漏洞利用 | sqlmap, nikto, wfuzz, ffuf, gobuster, wpscan |
| `agent_exploitation` | 漏洞利用 | metasploit, msfvenom, searchsploit, hydra, evil-winrm |
| `agent_password_crypto` | 密码破解 | hashcat, john, ophcrack, hydra, medusa, patator |
| `agent_wireless_attack` | 无线攻击 | airmon-ng, airodump-ng, aireplay-ng, aircrack-ng, kismet |
| `agent_reverse_engineering` | 逆向工程 | radare2, gdb, objdump, strings, binwalk |
| `agent_forensics` | 取证分析 | binwalk, foremost, scalpel, autopsy, volatility |
| `agent_post_exploitation` | 后渗透 | mimikatz, bloodhound, linpeas, winpeas, evil-winrm |
| `agent_custom_code` | 自定义代码 | python_execute工具 |
| `chat_agent` | 闲聊助手 | 无工具调用 |

## 支持的工具

### 信息收集 (Information Collection)
- **Amass**: 子域名枚举与攻击面发现
- **TheHarvester**: 基于公开数据源收集邮箱、子域名、IP
- **Recon-ng**: 模块化OSINT框架
- **SpiderFoot**: 自动化OSINT收集与关联分析
- **Fierce**: DNS枚举工具
- **Dnsenum**: DNS枚举与区域传送检测
- **Nbtscan**: NetBIOS主机信息探测
- **Arp-scan**: 局域网主机发现
- **Kismet**: 无线设备探测
- **Wafw00f**: Web应用防火墙识别

### 扫描 (Scanning)
- **Nmap**: 端口与服务识别
- **Masscan**: 高速端口扫描
- **Tcpdump**: 原始流量捕获
- **Tshark**: 命令行流量分析
- **Wireshark**: 图形化流量分析
- **Httpx**: Web服务探测
- **Gobuster**: 目录/子域爆破

### 枚举 (Enumeration)
- **Enum4linux**: SMB枚举
- **Dirb**: Web目录枚举
- **FFUF**: 参数/路径模糊测试
- **Wfuzz**: Web接口枚举
- **Nikto**: Web配置与漏洞枚举
- **WPScan**: WordPress枚举
- **Gobuster**: 目录/子域爆破
- **Curl**: HTTP响应验证

### Web利用 (Web Exploitation)
- **SQLMap**: SQL注入检测和利用
- **Nikto**: Web漏洞扫描
- **Wfuzz**: 参数与接口fuzz
- **FFUF**: 路径与参数爆破
- **Gobuster**: Web枚举辅助
- **WPScan**: WordPress漏洞

### 漏洞利用 (Exploitation)
- **Metasploit**: 漏洞利用框架
- **Msfvenom**: Payload生成
- **Searchsploit**: EXP搜索
- **Evil-WinRM**: Windows远程Shell
- **Hydra**: 在线爆破
- **Medusa**: 并行爆破
- **Patator**: 通用爆破框架
- **Responder**: 凭证捕获

### 密码破解 (Password & Crypto)
- **Hash-Identifier**: Hash类型识别
- **Hashcat**: GPU加速Hash破解
- **John**: 通用密码破解
- **Ophcrack**: 彩虹表破解
- **Hydra**: 在线口令爆破
- **Medusa**: 并行口令攻击
- **Patator**: 模块化爆破框架

### 无线攻击 (Wireless Attack)
- **Airmon-ng**: 无线网卡监听模式
- **Airodump-ng**: 无线数据包抓取
- **Aireplay-ng**: 重放与认证攻击
- **Aircrack-ng**: 无线密钥破解
- **Kismet**: 无线网络探测

## Web API

### REST API端点

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/` | Web界面主页 |
| GET | `/api/history` | 获取对话历史 |
| GET | `/api/history/summary` | 获取对话历史摘要 |
| GET | `/api/memory/stats` | 获取记忆统计信息 |
| POST | `/api/history/clear` | 清空对话历史 |
| POST | `/api/query` | 提交查询并执行Agent |
| GET | `/api/query/{task_id}/stream` | SSE流式输出 |

### 示例请求

**提交查询**:
```bash
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "扫描192.168.1.1的开放端口"}'
```

**获取历史**:
```bash
curl http://localhost:8000/api/history
```

## 配置说明

### LLM Provider配置

系统支持多种LLM Provider，通过 `.env` 文件中的 `LLM_PROVIDER` 变量切换：

```env
# 使用OpenRouter（默认）
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=your-key

# 使用OpenAI
LLM_PROVIDER=openai
OPENAI_API_KEY=your-key

# 使用DeepSeek
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=your-key

# 使用SiliconFlow
LLM_PROVIDER=siliconflow
SILICONFLOW_API_KEY=your-key

# 使用自定义Provider
LLM_PROVIDER=custom
CUSTOM_API_KEY=your-key
CUSTOM_BASE_URL=https://your-endpoint/v1
```

### 记忆管理配置

Memory Manager支持以下策略：
- **滑动窗口**: 保留最近的对话
- **重要性评估**: 保留重要的对话
- **总结机制**: 对旧对话进行总结
- **Token计数**: 精确控制上下文长度

默认配置：
- 最大token数: 根据模型自动设置（GPT-4: 8192, GPT-4-Turbo: 128000）
- 保留token: 1000（用于系统提示和当前查询）
- 总结阈值: 7天前的对话会被考虑总结
- 最小对话数: 5个对话后开始总结

## 安全注意事项

⚠️ **重要提醒**:

1. **授权测试**: 本工具仅用于授权的安全测试环境
2. **合法使用**: 在实际使用前，请确保获得合法的授权
3. **遵守法律**: 遵守当地法律法规和道德规范
4. **隔离环境**: 建议在隔离的测试环境中进行验证
5. **风险控制**: 工具直接在Kali Linux中执行命令，请谨慎使用

## 更新日志

详见 [CHANGELOG.md](CHANGELOG.md)

## 许可证

本项目仅供学习和研究使用。

### 使用示例

输入你的任务，例如：
- "扫描192.168.1.1的开放端口"
- "对http://example.com进行SQL注入测试"
- "枚举192.168.1.1的SMB共享"
- "写一段Python代码来扫描端口"（自定义代码执行）
- "帮我执行Python代码处理文件"（自定义代码执行）

### 对话历史功能

系统会在同一次运行中保持对话记忆，你可以：
- 连续提问，系统会记住之前的对话内容
- 输入 `history` 或 `历史` 查看对话历史
- 输入 `clear` 或 `清空` 清空对话历史
- 输入 `quit` 或 `exit` 退出程序

**示例：**
```
> 扫描192.168.1.1的开放端口
> 对刚才扫描到的80端口进行Web漏洞扫描
> 用刚才的结果继续深入测试
```

## 项目结构

```
SkidCon/
├── core/
│   ├── kali_executor.py         # Kali Linux直接执行器
│   ├── tools.py                 # 工具定义（kali_command, python_execute）
│   ├── level1_agent.py          # 一级Agent（任务分类）
│   ├── level2_agent.py          # 二级Agent（领域专家）
│   ├── level3_agent.py          # 三级Agent（工具列表）
│   ├── third_agent_factory.py   # 三级Agent工厂
│   ├── agent_runner.py          # Agent运行器
│   ├── memory_manager.py        # 记忆管理器
│   └── chat_agent.py            # 闲聊Agent
├── config/
│   ├── execute_config.py        # 执行配置（OpenRouter）
│   ├── tools_manuals.py         # 工具手册
│   └── tool_category_mapping.py # 工具分类映射
├── web/
│   ├── app.py                   # FastAPI后端
│   └── static/                  # Vue3构建产物
├── frontend/                    # Vue3+Vite前端
│   ├── src/
│   │   ├── App.vue              # 主组件
│   │   └── main.js              # 入口文件
│   ├── package.json
│   └── vite.config.js
├── skills/pocs/                 # PoC技能库（50+ CVE）
├── main.py                      # 入口文件
├── requirements.txt             # Python依赖
└── .env.example                 # 环境变量示例
```

## 工作流程

```
用户输入任务
    ↓
Level 1 Agent (任务分类)
    ↓
Level 2 Agent (选择工具)
    ↓
Level 3 Agent (执行工具)
    ↓
Kali Linux 直接执行
    ↓
返回结果
```

## 注意事项

- 所有代码执行直接在Kali Linux环境中，确保环境安全
- 确保Kali Linux中有相应的渗透测试工具
- API调用需要有效的OpenRouter API密钥
- 执行结果会实时流式输出
- 仅用于授权的安全测试环境
- 遵守当地法律法规和道德规范

## 获取OpenRouter API密钥

1. 访问 https://openrouter.ai/
2. 注册账号
3. 在Dashboard中创建API密钥
4. 将密钥添加到 `.env` 文件中

## 支持的模型

默认使用 `z-ai/glm-5.1` 模型，你可以在OpenRouter上选择其他支持的模型：
- anthropic/claude-3.5-sonnet
- openai/gpt-4o
- google/gemini-pro
- 等等...

修改 `.env` 文件中的 `MODEL_NAME` 即可切换模型。
# SkidCon（附hexstrike-ai docker下载链接）

一个基于三层Agent架构的容器代码执行系统，在 **Docker** 中执行渗透测试相关代码与命令行工具。

**运行环境说明：** 项目名里的 “Kali” 只是常见示例，**并不强制使用 Kali Linux 镜像**。你可以使用任意 Linux 基础的 Docker 镜像，只要在容器里**配备好 Agent 可能调用的安全工具**（如 nmap、sqlmap、metasploit 等，视任务与配置而定），并确保有 **`python3`** 与 **`bash`**，即可正常对接本项目的执行器。

## 架构说明

本项目采用三层Agent架构：

1. **Level 1 Agent (任务分类器)**: 将用户任务分类到不同的安全测试领域
2. **Level 2 Agent (领域专家)**: 每个领域有专门的专家Agent，负责选择合适工具
3. **Level 3 Agent (工具执行器)**: 每个工具都有专门的执行Agent，在Docker容器中执行代码

## 功能特性

- ✅ 三层Agent自动路由和执行
- ✅ 支持50+渗透测试工具（nmap, sqlmap, metasploit等）
- ✅ 在 Docker 容器中隔离执行（非 Kali 亦可，配齐工具即可）
- ✅ 流式输出，实时查看执行过程
- ✅ 支持多种安全测试领域（信息收集、扫描、枚举、Web利用等）

## 安装

1. 克隆项目：
```bash
cd Kali_Code_Excuter
```

2. 安装依赖：
```bash
pip install -r requirements.txt
```

3. 配置环境变量，创建 `.env` 文件：
```env
DOCKER_NAME=你的容器名称（任意镜像均可，需配备相应安全工具）
OPENAI_API_KEY=你的API密钥
OPENAI_BASE_URL=你的API地址
MODEL_NAME=gpt-4o
```

如果你没有**配置 Kali 容器**，或觉得**在 Kali 容器里安装工具很麻烦**，这里提供**已配置好的一键部署版本**，并非轻量级，请根据自身情况下载。强烈不建议在本机情况下直接运行执行器，链接如下：

- [Google Drive 一键部署资源](https://drive.google.com/file/d/1nHu7KkKcIu9lDdgMtiwRqX89zSwjm7tz/view?usp=drive_link)

## 使用方法

运行主程序：
```bash
python main.py
```

程序启动后会自动开启Web界面，访问 **http://localhost:8000** 即可在浏览器中查看对话历史。

### Web界面功能

- 📊 **实时对话历史展示**：自动更新，无需刷新
- 🔄 **WebSocket实时通信**：新消息自动推送到浏览器
- 📥 **导出对话历史**：支持导出为JSON格式
- 🗑️ **清空历史记录**：一键清空所有对话
- 📈 **统计信息**：显示总对话数和最后更新时间

然后输入你的任务，例如：
- "扫描192.168.1.1的开放端口"
- "对http://example.com进行SQL注入测试"
- "枚举192.168.1.1的SMB共享"
- "写一段Python代码来扫描端口"（自定义代码执行）
- "帮我执行Python代码处理文件"（自定义代码执行）

### 对话历史功能

系统会在同一次运行中保持对话记忆，你可以：
- 连续提问，系统会记住之前的对话内容
- 输入 `history` 或 `历史` 查看对话历史
- 输入 `clear` 或 `清空` 清空对话历史
- 输入 `quit` 或 `exit` 退出程序

**示例：**
```
> 扫描192.168.1.1的开放端口
> 对刚才扫描到的80端口进行Web漏洞扫描
> 用刚才的结果继续深入测试
```

## 项目结构

```
Kali_Code_Excuter/
├── core/
│   ├── docker_executor.py      # Docker执行器
│   ├── tools.py                 # 工具定义（python_execute）
│   ├── level1_agent.py          # 一级Agent（任务分类）
│   ├── level2_agent.py          # 二级Agent（领域专家）
│   ├── level3_agent.py          # 三级Agent（工具执行器）
│   ├── third_agent_factory.py   # 三级Agent工厂
│   └── agent_runner.py          # Agent运行器
├── config/
│   ├── execute_config.py        # 执行配置
│   └── tools_manuals.py         # 工具手册
├── main.py                      # 主入口
├── requirements.txt              # 依赖列表
└── README.md                    # 本文件
```

## 支持的领域

- 信息收集 (Information Collection)
- 扫描与服务发现 (Scanning)
- 枚举 (Enumeration)
- Web利用 (Web Exploitation)
- 漏洞利用 (Exploitation)
- 密码破解 (Password & Crypto)
- 无线攻击 (Wireless Attack)
- 逆向工程 (Reverse Engineering)
- 数字取证 (Forensics)
- 后渗透 (Post-Exploitation)
- **自定义代码执行 (Custom Code)** - 新增：可以自由编写和执行Python代码

## 注意事项

1. 确保 Docker 容器正在运行且可访问（不限 Kali；镜像内需有所需安全 CLI 与 `python3`）
2. 确保容器名称与 `.env` 中的 `DOCKER_NAME` 一致
3. 需要有效的OpenAI API密钥和地址，deepseek也行
4. 所有代码执行都在隔离的Docker容器中进行

## Todo
1. KILL未适配到对话系统中，相关代码待书写
2. Kali_Code_Excuter/config/tools_manuals.py里对应的工具说明书过于简略，详细的执行参数与few sht prompt待补全

## 许可证

MIT License
