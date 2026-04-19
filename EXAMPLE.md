# 使用示例

本文档提供SkidCon系统的详细使用示例，涵盖各种安全测试场景。

## 快速开始

### 1. 配置环境变量

创建 `.env` 文件：
```env
# LLM Provider配置
LLM_PROVIDER=openrouter
MODEL_NAME=z-ai/glm-5.1

# API密钥
OPENROUTER_API_KEY=你的OpenRouter API密钥

# Web服务配置
PORT=8000
LOG_LEVEL=INFO
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 运行程序

```bash
python main.py
```

程序启动后会自动开启Web界面，访问 **http://localhost:8000** 即可查看对话历史。

## 使用示例

### 示例1: 端口扫描

**输入**:
```
> 扫描192.168.1.1的开放端口
```

**系统执行流程**:
1. Level 1 Agent 识别为 "scanning" 任务
2. Level 2 Agent (Scanning Expert) 选择 nmap 工具
3. 执行命令: `nmap -sV 192.168.1.1`
4. 返回扫描结果

**预期输出**:
```
Starting Nmap 7.94 ( https://nmap.org )
Nmap scan report for 192.168.1.1
Host is up (0.0032s latency).
Not shown: 998 closed tcp ports (conn-refused)
PORT   STATE SERVICE VERSION
22/tcp open  ssh     OpenSSH 8.9p1
80/tcp open  http    Apache httpd 2.4.52
```

---

### 示例2: Web漏洞扫描

**输入**:
```
> 对http://example.com进行SQL注入测试
```

**系统执行流程**:
1. Level 1 Agent 识别为 "web_exploitation" 任务
2. Level 2 Agent (Web Exploitation Expert) 选择 sqlmap 工具
3. 执行命令: `sqlmap -u http://example.com --batch`
4. 返回SQL注入检测结果

---

### 示例3: 信息收集

**输入**:
```
> 收集example.com的子域名信息
```

**系统执行流程**:
1. Level 1 Agent 识别为 "information_collection" 任务
2. Level 2 Agent (Information Collection Expert) 选择 amass 工具
3. 执行命令: `amass enum -d example.com`
4. 返回子域名列表

---

### 示例4: 自定义代码执行

**输入**:
```
> 写一段Python代码来扫描192.168.1.1的80端口
```

或

```
> 帮我执行Python代码，读取/etc/passwd文件
```

**系统执行流程**:
1. Level 1 Agent 识别为 "custom_code" 任务
2. Level 2 Agent (Custom Code Executor) 直接执行Python代码
3. 代码在Kali Linux环境中运行，返回执行结果

**示例代码**:
```python
import socket

def scan_port(host, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    result = sock.connect_ex((host, port))
    if result == 0:
        print(f"Port {port} is open")
    else:
        print(f"Port {port} is closed")
    sock.close()

scan_port('192.168.1.1', 80)
```

---

### 示例5: 密码破解

**输入**:
```
> 使用hashcat破解这个hash: 5f4dcc3b5aa765d61d8327deb882cf99
```

**系统执行流程**:
1. Level 1 Agent 识别为 "password_crypto" 任务
2. Level 2 Agent (Password & Crypto Expert) 选择 hashcat 工具
3. 执行命令: `hashcat -m 0 -a 0 hash.txt rockyou.txt`
4. 返回破解结果

---

### 示例6: SMB枚举

**输入**:
```
> 枚举192.168.1.100的SMB共享
```

**系统执行流程**:
1. Level 1 Agent 识别为 "enumeration" 任务
2. Level 2 Agent (Enumeration Expert) 选择 enum4linux 工具
3. 执行命令: `enum4linux -a 192.168.1.100`
4. 返回SMB共享信息

---

### 示例7: 无线攻击

**输入**:
```
> 使用aircrack-ng破解WiFi密码
```

**系统执行流程**:
1. Level 1 Agent 识别为 "wireless_attack" 任务
2. Level 2 Agent (Wireless Attack Expert) 选择 aircrack-ng 工具链
3. 执行命令序列:
   - `airmon-ng start wlan0`
   - `airodump-ng wlan0mon`
   - `aireplay-ng -0 5 -a <AP_MAC> wlan0mon`
   - `aircrack-ng capture.cap -w wordlist.txt`
4. 返回破解结果

---

### 示例8: 漏洞利用

**输入**:
```
> 使用metasploit攻击目标系统的MS17-010漏洞
```

**系统执行流程**:
1. Level 1 Agent 识别为 "exploitation" 任务
2. Level 2 Agent (Exploitation Expert) 选择 metasploit 工具
3. 执行msfconsole命令
4. 返回利用结果

---

### 示例9: 后渗透

**输入**:
```
> 使用mimikatz提取Windows凭据
```

**系统执行流程**:
1. Level 1 Agent 识别为 "post_exploitation" 任务
2. Level 2 Agent (Post Exploitation Expert) 选择 mimikatz 工具
3. 执行命令提取凭据
4. 返回凭据信息

---

### 示例10: 闲聊模式

**输入**:
```
> 你好，你能做什么？
```

或

```
> 解释一下什么是SQL注入
```

**系统执行流程**:
1. Level 1 Agent 识别为闲聊任务 (action="chat")
2. 直接调用 Chat Agent
3. 返回自然语言回答（不调用工具）

---

## 高级使用场景

### 场景1: 完整渗透测试流程

**步骤1: 信息收集**
```
> 收集target.com的域名和子域名信息
```

**步骤2: 端口扫描**
```
> 扫描target.com的开放端口和服务
```

**步骤3: 服务枚举**
```
> 枚举target.com的Web目录和配置
```

**步骤4: 漏洞识别**
```
> 扫描target.com的已知漏洞
```

**步骤5: 漏洞利用**
```
> 利用发现的SQL注入漏洞
```

**步骤6: 后渗透**
```
> 提取系统凭据和敏感信息
```

---

### 场景2: CTF挑战

**输入**:
```
> 帮我解决这个CTF挑战，目标IP是10.10.10.10
```

**系统会自动**:
1. 识别为多阶段任务
2. 依次执行信息收集、扫描、枚举、利用
3. 返回每个阶段的发现

---

### 场景3: 批量扫描

**输入**:
```
> 扫描192.168.1.0/24网段的存活主机
```

**系统执行**:
1. 使用nmap进行网段扫描
2. 发现存活主机
3. 返回主机列表

---

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

### 三级Agent架构

1. **Level 1 Agent (任务分类器)**
   - 分析用户输入
   - 输出JSON决策（action和target）
   - 支持12个安全测试领域

2. **Level 2 Agent (领域专家)**
   - 每个领域一个专家Agent
   - 选择合适的工具
   - 生成并执行命令

3. **Level 3 Agent (工具执行器)**
   - KaliExecutor直接执行命令
   - 安全的命令执行机制
   - 超时和错误处理

### 支持的安全测试领域

| 领域 | 描述 | 主要工具 |
|------|------|----------|
| information_collection | 信息收集与OSINT | amass, theharvester, recon-ng |
| scanning | 网络扫描 | nmap, masscan, httpx |
| enumeration | 服务枚举 | enum4linux, dirb, ffuf, nikto |
| web_exploitation | Web漏洞利用 | sqlmap, nikto, wfuzz |
| exploitation | 漏洞利用 | metasploit, hydra, evil-winrm |
| password_crypto | 密码破解 | hashcat, john, ophcrack |
| wireless_attack | 无线攻击 | airmon-ng, airodump-ng, aircrack-ng |
| reverse_engineering | 逆向工程 | radare2, gdb, binwalk |
| forensics | 取证分析 | binwalk, foremost, volatility |
| post_exploitation | 后渗透 | mimikatz, bloodhound, linpeas |
| custom_code | 自定义代码 | python_execute |

## 注意事项

⚠️ **重要提醒**:

1. **授权测试**: 本工具仅用于授权的安全测试环境
2. **合法使用**: 在实际使用前，请确保获得合法的授权
3. **遵守法律**: 遵守当地法律法规和道德规范
4. **隔离环境**: 建议在隔离的测试环境中进行验证
5. **风险控制**: 工具直接在Kali Linux中执行命令，请谨慎使用

## 故障排除

### 常见问题

**Q: API密钥未设置错误**
A: 检查 `.env` 文件是否正确设置了 `OPENROUTER_API_KEY`

**Q: 命令执行失败**
A: 确保在Kali Linux环境中运行，且工具已安装

**Q: 前端无法访问**
A: 检查前端是否已构建，或运行 `cd frontend && npm run dev`

**Q: Token超出限制**
A: 系统会自动管理记忆，如需调整可修改 `memory_manager.py` 中的配置

## 更多资源

- [README.md](README.md) - 项目概述和安装指南
- [ARCHITECTURE.md](ARCHITECTURE.md) - 详细架构文档
- [API.md](API.md) - REST API文档
- [CHANGELOG.md](CHANGELOG.md) - 更新日志

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

