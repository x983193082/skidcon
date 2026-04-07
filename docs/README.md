# SkidCon - 基于CrewAI的自动化渗透测试系统

基于CrewAI框架的自动化渗透测试系统，采用多Agent协作架构，支持本地开发和Docker部署。

---

## 系统整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                           SkidCon                                  │
│                 (多Agent协作自动化渗透测试系统)                         │
└─────────────────────────────────────────────────────────────────────┘
                                    │
          ┌─────────────────────────┼─────────────────────────┐
          │                         │                         │
          ▼                         ▼                         ▼
┌───────────────────┐     ┌───────────────────┐     ┌───────────────────┐
│  Scanner Agent   │     │  Planner Agent   │     │ Executor Agent   │
│  (端口扫描Agent)  │────▶│  (决策制定Agent) │────▶│  (执行验证Agent) │
└───────────────────┘     └───────────────────┘     └───────────────────┘
          │                         │                         │
          ▼                         ▼                         ▼
┌───────────────────┐     ┌───────────────────┐     ┌───────────────────┐
│   Nmap Skill      │     │   分析扫描结果    │     │  执行渗透命令    │
│   端口扫描工具     │     │   制定策略       │     │  循环检测验证    │
│   Quick/Full      │     │   漏洞识别       │     │  寻找flag        │
└───────────────────┘     └───────────────────┘     └───────────────────┘
```

### 工作原理

1. **Scanner Agent (端口扫描Agent)**
   - 接收目标主机
   - 使用nmap工具进行端口扫描
   - 收集开放端口、服务版本信息
   - 识别中间件和框架类型
   - 输出详细扫描报告

2. **Planner Agent (决策制定Agent)**
   - 分析Scanner的扫描结果
   - 识别潜在漏洞（基于服务版本）
   - 制定渗透测试策略
   - 优先级排序攻击目标
   - 准备对应POC/EXP

3. **Executor Agent (执行验证Agent)**
   - 根据策略执行渗透命令
   - 验证每个步骤的结果
   - 循环检测直到找到flag或完成测试
   - 记录所有输出
   - 判断漏洞是否存在

### 协作流程

```
目标输入 → Scanner扫描 → Planner分析 → Executor执行
                            ↑              │
                            │              ▼
                            │         结果验证
                            │              │
                            └────── 循环检测┘
```

---

## 快速开始

### 1. 本地运行（开发模式）

```bash
# 安装依赖
pip install -r requirements.txt

# 配置API Key
# 访问 https://openrouter.ai/keys 获取API Key
# 编辑 .env 文件
OPENROUTER_API_KEY=你的API密钥

# 运行
python main.py --target 192.168.1.1

# 指定模型
python main.py --target 192.168.1.1 --model z-ai/glm-5

# 带详细输出
python main.py --target 192.168.1.1 --verbose

# 指定会话ID（用于恢复）
python main.py --target 192.168.1.1 --session my_session_001
```

### 2. Docker运行（生产模式）

```bash
# 构建镜像
docker build -t pentestai .

# 运行（单次）
docker run -it --rm \
  -e OPENROUTER_API_KEY=你的API密钥 \
  pentestai --target 192.168.1.1

# 使用docker-compose
# 1. 编辑 .env 文件填入API Key
# 2. 运行开发模式（本地目录映射）
docker-compose up dev

# 3. 运行生产模式（持久化存储）
docker-compose up prod
```

---

## 目录结构

```
pentest_ai/
├── __init__.py              # 包初始化文件
├── main.py                  # 主入口文件
├── requirements.txt         # Python依赖
├── Dockerfile               # Docker镜像定义
├── docker-compose.yml       # Docker编排配置
├── .env                     # 环境变量（API Key）
├── README.md                # 项目说明
├── agents/                  # Agent定义
│   ├── __init__.py
│   ├── scanner_agent.py      # 端口扫描Agent
│   ├── planner_agent.py     # 决策制定Agent
│   └── executor_agent.py    # 执行验证Agent
├── skills/                  # Skill工具（可扩展）
│   ├── __init__.py
│   └── nmap_tool.py         # Nmap扫描工具
├── tools/                   # 其他工具
│   ├── __init__.py
│   └── base_tools.py        # 基础工具（可扩展）
├── prompts/                 # Prompt定义
│   ├── __init__.py
│   ├── scanner_prompts.py   # Scanner提示词
│   ├── planner_prompts.py   # Planner提示词
│   └── executor_prompts.py  # Executor提示词
├── crew/                    # Crew编排
│   └── pentest_crew.py      # 主Crew系统
├── utils/                   # 工具模块
│   └── config.py            # 配置管理、日志、结果
├── logs/                    # 日志目录（自动生成）
├── results/                 # 结果目录（自动生成）
└── workspace/                # 工作目录
```

---

## 各文件作用说明

### agents/ - Agent定义

| 文件 | 作用 |
|------|------|
| `scanner_agent.py` | 定义Scanner Agent，集成nmap工具进行端口扫描和信息收集 |
| `planner_agent.py` | 定义Planner Agent，分析扫描结果，制定渗透测试策略 |
| `executor_agent.py` | 定义Executor Agent，执行渗透命令并验证结果，循环检测 |

### skills/ - Skill工具（可扩展）

| 文件 | 作用 |
|------|------|
| `nmap_tool.py` | Nmap端口扫描工具，提供三种扫描模式：标准扫描、快速扫描、全面扫描 |

### tools/ - 其他工具（可扩展）

| 文件 | 作用 |
|------|------|
| `base_tools.py` | 基础工具类，包括SubprocessTool、ReconTool、WebDiscoveryTool等 |

### prompts/ - Prompt提示词

| 文件 | 作用 |
|------|------|
| `scanner_prompts.py` | Scanner Agent的系统提示词，定义信息收集任务、输出格式 |
| `planner_prompts.py` | Planner Agent的系统提示词，定义漏洞分析策略、优先级排序 |
| `executor_prompts.py` | Executor Agent的系统提示词，定义执行逻辑、循环检测、结果判断 |

### crew/ - Crew编排

| 文件 | 作用 |
|------|------|
| `pentest_crew.py` | 主Crew编排系统，协调三个Agent协作，处理任务分配和结果汇总 |

### utils/ - 工具模块

| 文件 | 作用 |
|------|------|
| `config.py` | 配置管理，处理API Key、模型配置、日志生成、结果保存 |

---

## 命令行参数

| 参数 | 简写 | 说明 | 默认值 |
|------|------|------|--------|
| `--target` | `-t` | 目标主机 (IP或域名) | 必填 |
| `--model` | `-m` | 使用的LLM模型 | z-ai/glm-5 |
| `--verbose` | `-v` | 详细输出 | False |
| `--interactive` | `-i` | 交互模式 | False |
| `--session` | `-s` | 指定会话ID | 自动生成 |

---

## 使用方法

### Python API使用

```python
# 基本使用
from pentest_ai import run_pentest

# 运行渗透测试
result = run_pentest(target="192.168.1.1")
print(result)
```

```python
# 高级使用
from pentest_ai.crew import PentestCrew
from pentest_ai.utils import get_openrouter_llm

# 自定义模型
llm = get_openrouter_llm("z-ai/glm-5")

# 创建Crew
crew = PentestCrew(
    target="10.0.0.1",
    model="z-ai/glm-5"
)

# 执行
result = crew.kickoff()
```

### 日志和结果

- **日志文件**: `logs/pentest_{会话ID}.log`
- **结果文件**: `results/result_{会话ID}.json`

---

## 配置说明

### 环境变量

在 `.env` 文件中配置：

```bash
# OpenRouter API Key（必填）
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxx

# 默认模型
DEFAULT_MODEL=z-ai/glm-5
```

### 可用模型

| 模型 | 说明 | 价格 |
|------|------|------|
| `z-ai/glm-5` | 智谱GLM-5 (默认) | 免费 |

---

## Prompt编写指南

### Scanner Agent Prompt结构

```python
SCANNER_AGENT_PROMPT = """你是PentestAI的信息收集专家，擅长网络侦察和端口扫描。

## 终极目标
收集完整的目标信息，包括：
- 开放端口和服务
- 服务版本和指纹
- 潜在的入口点
- 识别的框架和中间件

## 核心职责
1. 端口扫描
2. 服务识别
3. 信息收集
4. 漏洞识别

## 可用工具
- nmap_port_scanner: 标准端口扫描
- quick_nmap_scan: 快速扫描常用端口
- full_nmap_scan: 全面扫描

## 输出格式要求
## 信息收集报告
### 端口扫描结果
| 端口 | 服务 | 版本 | 状态 |
### 识别的中间件
### 潜在漏洞
### 建议测试
"""
```

### Planner Agent Prompt结构

```python
PLANNER_AGENT_PROMPT = """你是PentestAI的渗透策略专家，擅长分析扫描结果并制定攻击计划。

## 终极目标
分析目标环境，识别所有可能的攻击向量，并按风险程度排序。

## 核心职责
1. 漏洞识别
2. 攻击规划
3. 环境判断

## 分析框架
- 服务分析: 分析每个服务的用途和已知漏洞
- 版本分析: 检查版本是否存在已知CVE
- 攻击面分析: 识别所有可能的入口点

## 输出格式
## 渗透测试计划
### 环境分析
### 攻击面
### 漏洞测试优先级
### 测试计划
"""
```

### Executor Agent Prompt结构

```python
EXECUTOR_AGENT_PROMPT = """你是PentestAI的渗透测试执行专家，擅长执行漏洞利用并验证结果。

## 终极目标
你的任务不完整于找到漏洞或flag。即使目标没有漏洞，也要完整测试并报告测试结果。

## 核心职责
1. 漏洞验证
2. 结果验证
3. 循环测试

## 漏洞判断标准
### 漏洞存在
- POC执行成功，返回预期输出
- 获得命令执行结果
- 获取反弹shell

### 漏洞不存在
- POC执行返回错误
- 超时无响应
- 所有POC尝试均失败

## 测试循环逻辑
for each vulnerability in test_plan:
    for each POC in vulnerability.POCs:
        result = execute(POC)
        if result.is_vulnerable:
            try_get_shell()
        else:
            continue
    report_vulnerability_not_exists()
"""
```

---

## 扩展指南

### 添加新的Skill/Tool

1. 在 `skills/` 目录下创建新的工具文件:

```python
# skills/my_tool.py
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Type
import subprocess

class MyToolInput(BaseModel):
    target: str = Field(description="目标主机")
    options: str = Field(default="", description="额外选项")

class MyTool(BaseTool):
    name: str = "my_tool"
    description: str = "工具描述，说明工具的用途"
    args_schema: Type[BaseModel] = MyToolInput

    def _run(self, target: str, options: str = "") -> str:
        # 实现逻辑
        cmd = ["命令", "参数", target]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.stdout

# 导出
my_tool = MyTool()
```

2. 在Agent中使用:

```python
# agents/scanner_agent.py
from ..skills.my_tool import MyTool

class ScannerAgent(Agent):
    def __init__(self, llm, **kwargs):
        tools = [
            NmapTool(),
            QuickNmapTool(),
            MyTool()  # 添加新工具
        ]
        super().__init__(tools=tools, llm=llm, **kwargs)
```

### 添加新的Agent

1. 在 `agents/` 目录下创建新的Agent:

```python
# agents/new_agent.py
from crewai import Agent
from ..prompts.new_agent_prompts import NEW_AGENT_PROMPT

class NewAgent(Agent):
    def __init__(self, llm, **kwargs):
        super().__init__(
            name="New Agent",
            role="角色名称",
            goal="Agent的目标",
            backstory=NEW_AGENT_PROMPT,
            verbose=True,
            allow_delegation=False,
            llm=llm,
            **kwargs
        )
```

2. 创建对应的Prompt文件:

```python
# prompts/new_agent_prompts.py
NEW_AGENT_PROMPT = """描述Agent的背景和能力..."""
```

3. 在Crew中注册:

```python
# crew/pentest_crew.py
from ..agents.new_agent import NewAgent

class PentestCrew:
    def _setup_agents(self):
        self.new_agent = NewAgent(llm=self.llm)
        
        self.crew = Crew(
            agents=[
                self.scanner_agent,
                self.planner_agent,
                self.executor_agent,
                self.new_agent  # 添加新Agent
            ],
            tasks=[...],
            ...
        )
```

### 添加新的漏洞环境

在 `prompts/planner_prompts.py` 中添加：

```python
### 新框架漏洞
- **框架名**: 对应漏洞列表
  - CVE-XXXX-XXXX: 描述
  - 影响版本: x.x-x.x
```

在 `prompts/executor_prompts.py` 中添加对应POC：

```python
### 新框架漏洞测试
poc_example = """
# POC说明
curl http://target/poc
"""
```

---

## 注意事项

1. **仅用于授权测试**: 本工具仅用于授权的安全测试，禁止用于非法渗透
2. **API Key安全**: 不要将API Key提交到公开仓库，使用.gitignore忽略.env文件
3. **网络流量**: 渗透测试会产生大量网络流量，确保遵守目标网络政策
4. **日志记录**: 系统会记录所有操作，请妥善保管日志和结果文件
5. **靶场环境**: Vulhub等靶场可能没有漏洞，这是正常现象，只需完整测试并报告

---

## 许可证

MIT License
