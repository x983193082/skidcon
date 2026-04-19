# SkidCon 架构文档

本文档详细描述SkidCon系统的架构设计、模块职责和数据流。

## 系统架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                        用户界面层                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  终端CLI     │  │  Web界面     │  │  REST API    │       │
│  │  (main.py)   │  │  (Vue3)      │  │  (FastAPI)   │       │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
└─────────┼────────────────┼─────────────────┼────────────────┘
          │                │                 │
          └────────────────┼─────────────────┘
                           │
┌──────────────────────────┼──────────────────────────────────┐
│                     核心调度层                                │
│                        ▼                                     │
│              ┌─────────────────────┐                         │
│              │   AgentRunner       │                         │
│              │  (三级Agent调度器)   │                         │
│              └────────┬────────────┘                         │
│                       │                                      │
│         ┌─────────────┼─────────────┐                       │
│         ▼             ▼             ▼                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                  │
│  │ Level 1  │  │ Level 2  │  │  Chat    │                  │
│  │ Classifier│ │ Experts  │  │  Agent   │                  │
│  └──────────┘  └──────────┘  └──────────┘                  │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────┼──────────────────────────────────┐
│                     工具执行层                                │
│                        ▼                                     │
│              ┌─────────────────────┐                         │
│              │   KaliExecutor      │                         │
│              │  (命令执行器)        │                         │
│              └────────┬────────────┘                         │
│                       │                                      │
│         ┌─────────────┼─────────────┐                       │
│         ▼             ▼             ▼                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                  │
│  │subprocess│  │  Python  │  │  安全    │                  │
│  │  执行    │  │  执行    │  │  检查    │                  │
│  └──────────┘  └──────────┘  └──────────┘                  │
└────────────────────────────────────────────────────────────┘
                           │
┌──────────────────────────┼──────────────────────────────────┐
│                     辅助系统层                                │
│                        ▼                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │ Memory   │  │ Decision │  │ Result   │  │ Report   │    │
│  │ Manager  │  │ Engine   │  │ Verifier │  │ Generator│    │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                  │
│  │ Test     │  │ Planning │  │  PoC     │                  │
│  │ State    │  │ Agent    │  │  Skills  │                  │
│  └──────────┘  └──────────┘  └──────────┘                  │
└────────────────────────────────────────────────────────────┘
```

## 模块详细说明

### 1. 主入口模块 (`main.py`)

**职责**:
- 程序启动入口
- 环境变量检查
- Web服务器后台启动
- 交互式CLI循环

**关键函数**:
- `start_web_server()`: 在后台线程启动Uvicorn服务器
- `main()`: 主函数，处理用户交互循环

**数据流**:
```
用户输入 → 检查环境变量 → 启动Web服务器 → 进入交互循环 → 调用AgentRunner
```

### 2. 配置模块 (`config/`)

#### 2.1 `execute_config.py` - LLM配置

**职责**:
- 多Provider支持（OpenRouter、OpenAI、DeepSeek、SiliconFlow、Custom）
- API密钥和Base URL管理
- LLM配置字典生成

**支持的Provider**:
```python
SUPPORTED_PROVIDERS = {
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "env_key": "OPENROUTER_API_KEY"},
    "openai": {"base_url": "https://api.openai.com/v1", "env_key": "OPENAI_API_KEY"},
    "deepseek": {"base_url": "https://api.deepseek.com/v1", "env_key": "DEEPSEEK_API_KEY"},
    "siliconflow": {"base_url": "https://api.siliconflow.cn/v1", "env_key": "SILICONFLOW_API_KEY"},
    "custom": {"base_url": None, "env_key": "CUSTOM_API_KEY"},
}
```

**配置优先级**:
1. `LLM_API_KEY` (通用)
2. Provider特定密钥 (如 `OPENROUTER_API_KEY`)
3. 默认值 (OpenRouter)

#### 2.2 `tool_category_mapping.py` - 工具类别映射

**职责**:
- 工具名称到安全测试类别的映射
- 支持工具别名（如 `the-harvester` → `theharvester`）
- 一级Agent分类参考

**映射结构**:
```python
TOOL_TO_CATEGORY = {
    "nmap": "scanning",
    "sqlmap": "web_exploitation",
    "hashcat": "password_crypto",
    # ... 50+ 工具映射
}
```

#### 2.3 `tools_manuals.py` - 工具手册

**职责**:
- 每个工具的描述信息
- 工具使用手册
- 返回格式定义（JSON Schema）

**手册结构**:
```python
TOOL_MANUALS = {
    "nmap": {
        "description": "端口与服务识别工具",
        "manual": "使用命令行方式调用 nmap...",
        "return_format": {
            "type": "json",
            "schema": {...}
        }
    },
    # ... 更多工具
}
```

### 3. 核心模块 (`core/`)

#### 3.1 `agent_runner.py` - Agent运行器

**职责**:
- 三级Agent调度核心
- 任务路由和分发
- 输出收集和流式推送
- 对话历史管理

**关键类**:
```python
class AgentRunner:
    def __init__(self, model_name: str)
    def process_query(self, query: str, task_id: str = None) -> str
    def route_and_run_level2(self, query: str, task_id: str = None)
    def _run_agent(self, agent: Agent, query: str, task_id: str = None) -> str
    def clear_history(self)
    def get_history_summary(self) -> str
```

**TARGET_TO_AGENT映射**:
```python
TARGET_TO_AGENT = {
    "information_collection": agent_information_collection,
    "scanning": agent_scanning,
    "enumeration": agent_enumeration,
    "web_exploitation": agent_web_exploitation,
    "exploitation": agent_exploitation,
    "password_crypto": agent_password_crypto,
    "wireless_attack": agent_wireless_attack,
    "reverse_engineering": agent_reverse_engineering,
    "forensics": agent_forensics,
    "post_exploitation": agent_post_exploitation,
    "custom_code": agent_custom_code,
}
```

**执行流程**:
1. 构建包含历史记录的查询
2. 运行Level 1 Agent获取JSON决策
3. 解析JSON提取action和target
4. 如果action=chat，调用Chat Agent
5. 如果action=handoff，根据target映射到Level 2 Agent
6. 运行Level 2 Agent执行工具
7. 收集并返回结果

#### 3.2 `level1_agent.py` - 任务分类器

**职责**:
- 分析用户输入
- 分类到正确的安全测试领域
- 输出结构化JSON决策

**Agent配置**:
```python
task_classifier_agent = Agent(
    role="CTF任务总控专家（一级Agent）",
    goal="将用户任务分类到正确的安全测试领域",
    backstory="""...""",
    llm=create_llm(),
    verbose=True,
    allow_delegation=False,
)
```

**输出格式**:
```json
{
  "action": "handoff",  // 或 "chat"
  "target": "scanning"  // 或 null（当action=chat时）
}
```

**分类规则**:
- 工具相关任务 → action="handoff", target=<类别>
- 闲聊/普通问题 → action="chat", target=null

#### 3.3 `level2_agent.py` - 领域专家 (12个Agent)

**职责**:
- 每个领域一个专家Agent
- 选择合适的工具
- 生成并执行命令
- 返回执行结果

**Agent列表**:

| Agent | 领域 | 工具数量 | 主要工具 |
|-------|------|----------|----------|
| `agent_information_collection` | 信息收集与OSINT | 11 | amass, theharvester, recon-ng |
| `agent_scanning` | 网络扫描 | 8 | nmap, masscan, httpx |
| `agent_enumeration` | 服务枚举 | 11 | enum4linux, dirb, ffuf, nikto |
| `agent_web_exploitation` | Web漏洞利用 | 7 | sqlmap, nikto, wfuzz |
| `agent_exploitation` | 漏洞利用 | 8 | metasploit, hydra, evil-winrm |
| `agent_password_crypto` | 密码破解 | 7 | hashcat, john, ophcrack |
| `agent_wireless_attack` | 无线攻击 | 5 | airmon-ng, airodump-ng, aircrack-ng |
| `agent_reverse_engineering` | 逆向工程 | 5 | radare2, gdb, binwalk |
| `agent_forensics` | 取证分析 | 5 | binwalk, foremost, volatility |
| `agent_post_exploitation` | 后渗透 | 6 | mimikatz, bloodhound, linpeas |
| `agent_custom_code` | 自定义代码 | 1 | python_execute |

**共同特征**:
- 都使用 `kali_command` 工具（除custom_code使用 `python_execute`）
- 都有严格的backstory规则（禁止直接输出答案，必须调用工具）
- 都使用相同的LLM配置

#### 3.4 `chat_agent.py` - 闲聊助手

**职责**:
- 处理不需要工具调用的问题
- 提供自然语言回答
- 拒绝高风险/违法操作请求

**配置**:
```python
chat_agent = Agent(
    role="闲聊助手",
    goal="回答用户不需要工具的问题",
    backstory="""...""",
    llm=create_llm(),
    verbose=True,
    allow_delegation=False,
)
```

#### 3.5 `kali_executor.py` - Kali命令执行器

**职责**:
- 在Kali Linux中安全执行命令
- 捕获stdout和stderr
- 处理超时和错误

**关键方法**:
```python
class KaliExecutor:
    def __init__(self, timeout: int = 300)
    def execute(self, command: str, working_dir: Optional[str] = None) -> str
    def execute_python(self, code: str) -> str
```

**安全机制**:
- 使用 `shlex.split()` 分割命令，防止注入
- `shell=False` 防止shell注入
- 超时控制（默认300秒）
- 错误处理和返回码检查

**返回格式**:
```
成功: stdout内容
失败: ⚠️ [Exit Code N]\nstdout\n--- STDERR ---\nstderr
超时: ❌ [Timeout] 命令执行超时 (300秒)
未找到: ❌ [Command Not Found] 命令不存在: <command>
```

#### 3.6 `tools.py` - CrewAI工具定义

**职责**:
- 定义CrewAI可使用的工具
- 封装KaliExecutor为CrewAI工具

**工具定义**:
```python
class KaliCommandTool(BaseTool):
    name: str = "kali_command"
    description: str = "Execute shell commands directly in Kali Linux environment..."
    args_schema: Type[BaseModel] = KaliCommandInput
    
class PythonExecuteTool(BaseTool):
    name: str = "python_execute"
    description: str = "Execute Python code directly in Kali Linux environment..."
    args_schema: Type[BaseModel] = PythonExecuteInput
```

**输入Schema**:
```python
class KaliCommandInput(BaseModel):
    command: str = Field(..., description="The shell command to execute...")
    rationale: str = Field("", description="Optional explanation...")

class PythonExecuteInput(BaseModel):
    code: str = Field(..., description="Python code to execute")
    rationale: str = Field("", description="Optional explanation...")
```

#### 3.7 `memory_manager.py` - 智能记忆管理

**职责**:
- 管理对话历史，避免超出token限制
- 支持多种记忆策略
- Token计数和上下文控制

**关键类**:
```python
class MemoryManager:
    def __init__(self, model_name: str = "gpt-4", max_tokens: int = None)
    def add_conversation(self, user_query: str, ai_response: Optional[str] = None)
    def build_context(self, current_query: str) -> str
    def _count_tokens(self, text: str) -> int
    def _summarize_conversations(self) -> str
```

**记忆策略**:

1. **滑动窗口**: 保留最近的对话
2. **重要性评估**: 保留重要的对话（importance_score 0-1）
3. **总结机制**: 对旧对话进行总结
4. **Token计数**: 精确控制上下文长度

**配置参数**:
```python
max_tokens = 根据模型自动设置（GPT-4: 8192, GPT-4-Turbo: 128000）
reserved_tokens = 1000  # 保留给系统提示和当前查询
summary_threshold_days = 7  # 7天前的对话会被考虑总结
min_conversations_before_summary = 5  # 最少保留5个对话再开始总结
```

**Token计算**:
- 使用tiktoken库（支持GPT模型）
- 回退估算：中文字符≈1.5 token，英文单词≈1.3 token

**对话条目结构**:
```python
@dataclass
class ConversationEntry:
    user_query: str
    ai_response: Optional[str]
    timestamp: datetime
    importance_score: float = 1.0  # 重要性评分 (0-1)
    token_count: int = 0  # 总token数
    summary: Optional[str] = None  # 总结内容
    is_summarized: bool = False  # 是否已被总结
```

#### 3.8 `decision_engine.py` - 决策引擎

**职责**:
- 决定下一步测试行动
- 基于当前测试状态规划下一步
- 自动推进渗透测试流程

**关键类**:
```python
class DecisionEngine:
    PHASE_ORDER = [
        "reconnaissance", "scanning", "enumeration",
        "vulnerability", "exploitation", "post_exploitation", "reporting"
    ]
    
    def decide_next_action(self, state: TestState) -> Decision
```

**阶段动作映射**:
```python
PHASE_ACTIONS = {
    "reconnaissance": [
        {"condition": lambda s: len(s.discovered_hosts) == 0,
         "action": "使用nmap扫描目标网段发现存活主机",
         "category": "information_collection"},
        {"condition": lambda s: len(s.discovered_hosts) > 0,
         "action": "对发现的主机进行DNS反向解析",
         "category": "information_collection"},
    ],
    "scanning": [...],
    "enumeration": [...],
    # ...
}
```

**决策输出**:
```python
@dataclass
class Decision:
    action: str          # 下一步动作
    category: str        # 工具类别
    next_phase: str      # 下一阶段
    reasoning: str       # 推理过程
    source: str          # 决策来源
    is_complete: bool = False  # 是否完成
```

#### 3.9 `result_verifier.py` - 结果验证器

**职责**:
- 验证工具执行结果的有效性
- 基于关键词和数据模式判断成功/失败
- 提供置信度评估

**关键类**:
```python
class ResultVerifier:
    def verify_result(self, category: str, result: str) -> VerificationResult
```

**验证规则结构**:
```python
VERIFICATION_RULES = {
    "information_collection": {
        "success_keywords": ["found", "discovered", "identified", ...],
        "failure_keywords": ["timeout", "unreachable", "down", ...],
        "data_patterns": [r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}"],
    },
    "scanning": {...},
    "enumeration": {...},
    "vulnerability": {...},
    # ...
}
```

**验证结果**:
```python
@dataclass
class VerificationResult:
    verified: bool       # 是否验证成功
    confidence: float    # 置信度 (0-1)
    evidence: str        # 证据
    details: Dict[str, Any]  # 详细信息
```

#### 3.10 `report_generator.py` - 报告生成器

**职责**:
- 生成结构化渗透测试报告
- 支持JSON和Markdown格式
- 包含执行摘要、发现、统计、时间线、建议

**关键类**:
```python
class ReportGenerator:
    def generate(self, state: TestState) -> str  # JSON格式
    def generate_markdown(self, state: TestState) -> str  # Markdown格式
```

**报告结构**:
```json
{
  "report_info": {
    "generated_at": "ISO时间",
    "tool": "SkidCon - AI Penetration Testing Assistant",
    "version": "1.0"
  },
  "executive_summary": "执行摘要",
  "target_info": {
    "target": "目标",
    "start_time": "开始时间",
    "end_time": "结束时间",
    "duration": "持续时间"
  },
  "findings": {
    "hosts": ["发现的主机"],
    "services": ["发现的服务"],
    "vulnerabilities": ["发现的漏洞"],
    "credentials": ["发现的凭据"]
  },
  "statistics": {
    "total_steps": 总步骤数,
    "hosts_discovered": 主机数,
    "services_discovered": 服务数,
    "vulnerabilities_found": 漏洞数,
    "credentials_found": 凭据数,
    "phases_completed": 完成阶段数
  },
  "timeline": ["时间线"],
  "recommendations": ["修复建议"]
}
```

**严重性等级**:
```python
SEVERITY_COLORS = {
    "critical": "#dc3545",  # 红色
    "high": "#fd7e14",      # 橙色
    "medium": "#ffc107",    # 黄色
    "low": "#28a745",       # 绿色
    "info": "#17a2b8"       # 青色
}
```

#### 3.11 `test_state.py` - 测试状态管理

**职责**:
- 结构化存储渗透测试发现
- 跟踪测试进度和状态
- 记录执行步骤

**关键类**:
```python
class TestState:
    PHASES = [
        "reconnaissance", "scanning", "enumeration",
        "vulnerability", "exploitation", "post_exploitation", "reporting"
    ]
    
    def __init__(self)
    def add_step(self, phase: str, query: str, result: str, verified: bool, category: str)
    def add_host(self, host: str)
    def add_service(self, service: ServiceInfo)
    def add_vulnerability(self, vuln: VulnerabilityInfo)
    def add_credential(self, cred: CredentialInfo)
```

**数据结构**:
```python
@dataclass
class ServiceInfo:
    host: str
    port: int
    service: str
    version: Optional[str] = None
    banner: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

@dataclass
class VulnerabilityInfo:
    name: str
    severity: str
    host: Optional[str] = None
    port: Optional[int] = None
    description: Optional[str] = None
    evidence: Optional[str] = None
    cve: Optional[str] = None

@dataclass
class CredentialInfo:
    username: str
    password: Optional[str] = None
    hash: Optional[str] = None
    service: Optional[str] = None
    source: Optional[str] = None

@dataclass
class ExecutedStep:
    step: int
    phase: str
    query: str
    result: str
    result_summary: str
    verified: bool
    category: str
    timestamp: datetime = field(default_factory=datetime.now)
```

#### 3.12 `planning_agent.py` - 渗透测试规划器

**职责**:
- 生成标准渗透测试计划
- 定义各阶段目标和工具
- 识别目标类型（IP、域名、URL等）

**关键类**:
```python
class PenetrationTestPlanner:
    STANDARD_PHASES = [
        TestPhase(name="reconnaissance", ...),
        TestPhase(name="scanning", ...),
        TestPhase(name="enumeration", ...),
        TestPhase(name="vulnerability", ...),
        TestPhase(name="exploitation", ...),
        TestPhase(name="post_exploitation", ...),
        TestPhase(name="reporting", ...),
    ]
    
    TARGET_TYPE_PATTERNS = {
        "ip": r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$",
        "ip_range": r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/\d{1,2}$",
        "domain": r"^[a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}$",
        # ...
    }
```

### 4. Web模块 (`web/`)

#### 4.1 `app.py` - FastAPI应用

**职责**:
- 提供REST API
- 服务静态前端文件
- 处理SSE流式输出
- 管理查询任务状态

**API端点**:
```python
@app.get("/")                      # 主页
@app.get("/api/history")           # 获取对话历史
@app.get("/api/history/summary")   # 获取历史摘要
@app.get("/api/memory/stats")      # 获取记忆统计
@app.post("/api/history/clear")    # 清空历史
@app.post("/api/query")            # 提交查询
@app.get("/api/query/{task_id}/stream")  # SSE流式输出
```

**任务管理**:
```python
query_tasks: Dict[str, Dict[str, Any]] = {}
```

**SSE流式输出**:
- 使用 `asyncio.Queue` 存储输出事件
- 支持多种事件类型：agent_thinking, agent_message, tool_call, tool_output
- 实时推送到前端

### 5. 前端模块 (`frontend/`)

#### 5.1 技术栈

- **框架**: Vue 3 (Composition API)
- **构建工具**: Vite 5
- **HTTP客户端**: Axios
- **Markdown渲染**: marked
- **代码高亮**: highlight.js

#### 5.2 主要组件 (`App.vue`)

**功能**:
- 聊天界面
- 消息渲染（支持Markdown）
- 流式输出显示
- Agent状态展示
- 工具调用可视化
- 自主测试模式
- 历史导出

**消息类型**:
- `user`: 用户消息
- `agent_status`: Agent状态
- `tool_call`: 工具调用
- `tool_output`: 工具输出
- `ai`: AI回复

**关键特性**:
- 实时流式输出（SSE）
- Markdown渲染
- 代码高亮
- 自动滚动
- 响应式设计

### 6. PoC技能库 (`skills/pocs/`)

**职责**:
- 存储CVE漏洞利用技能
- 提供技能导航
- 标准化技能格式

**目录结构**:
```
skills/pocs/
├── navigation.md          # 技能导航
├── README.md              # 使用说明
├── apache_log4j/
│   ├── navigation.md      # Log4j技能导航
│   └── cve_2021_44228.md  # Log4Shell技能
├── apache_http_server/
│   ├── navigation.md
│   └── cve_2021_42013.md
└── ...
```

**技能文件格式**:
```markdown
---
name: cve_2021_44228
description: Log4Shell漏洞利用
---

## 验证方法
...

## 利用方法
...

## 前提条件
...
```

## 数据流详解

### 查询处理流程

```
1. 用户输入查询
   ↓
2. main.py 接收输入
   ↓
3. AgentRunner.process_query()
   ├─ 创建task_id
   ├─ 保存用户消息
   └─ 调用 route_and_run_level2()
   ↓
4. route_and_run_level2()
   ├─ 构建包含历史的查询 (memory_manager.build_context)
   ├─ 运行 Level 1 Agent
   │  ├─ 创建 Task 和 Crew
   │  └─ 执行 kickoff()
   ├─ 提取JSON决策
   ├─ 解析 action 和 target
   └─ 分支处理：
      ├─ action=chat → 运行 Chat Agent
      └─ action=handoff → 运行对应 Level 2 Agent
   ↓
5. Level 2 Agent 执行
   ├─ 创建 Task 和 Crew
   ├─ Agent选择工具
   ├─ 调用 kali_command 工具
   │  └─ KaliExecutor.execute()
   │     ├─ shlex.split(command)
   │     ├─ subprocess.run()
   │     └─ 返回结果
   └─ 返回执行结果
   ↓
6. 结果处理
   ├─ 保存AI回复
   ├─ 更新记忆
   └─ 返回结果
```

### 流式输出流程

```
1. Web API 接收查询 (/api/query)
   ↓
2. 创建 asyncio.Queue
   ↓
3. 在后台任务中执行 AgentRunner.process_query()
   ↓
4. AgentRunner 通过 _add_output_sync() 添加输出
   ↓
5. 输出事件推送到 Queue
   ↓
6. SSE端点 (/api/query/{task_id}/stream) 读取 Queue
   ↓
7. 前端接收SSE事件并实时更新UI
```

## 安全设计

### 命令执行安全

1. **命令分割**: 使用 `shlex.split()` 防止注入
2. **禁用Shell**: `shell=False` 防止shell注入
3. **超时控制**: 默认300秒超时
4. **错误处理**: 捕获所有异常并返回友好错误

### API安全

1. **CORS**: 允许所有来源（开发模式）
2. **输入验证**: 查询不能为空
3. **错误处理**: 捕获异常并返回错误信息

### 记忆安全

1. **Token限制**: 避免超出模型上下文限制
2. **总结机制**: 对旧对话进行总结，保留关键信息
3. **重要性评估**: 保留重要的对话

## 扩展性设计

### 添加新的Level 2 Agent

1. 在 `level2_agent.py` 中定义新的Agent
2. 在 `agent_runner.py` 的 `TARGET_TO_AGENT` 中添加映射
3. 在 `tool_category_mapping.py` 中添加类别说明
4. 在 `tools_manuals.py` 中添加工具手册

### 添加新的工具

1. 在 `tools_manuals.py` 中添加工具手册
2. 在 `tool_category_mapping.py` 中添加映射
3. 在对应Level 2 Agent的backstory中添加工具描述

### 添加新的LLM Provider

1. 在 `execute_config.py` 的 `SUPPORTED_PROVIDERS` 中添加配置
2. 在 `.env` 中设置相应的API密钥
3. 设置 `LLM_PROVIDER` 环境变量

## 性能优化

### Token管理

- 使用tiktoken精确计算token数
- 滑动窗口保留最近对话
- 总结机制压缩旧对话
- 保留1000 token给系统提示

### 异步处理

- Web服务器在后台线程运行
- SSE流式输出使用asyncio.Queue
- 查询任务异步执行

### 缓存

- 工具实例缓存（避免重复创建）
- LLM实例缓存
- 对话历史缓存

## 监控和日志

### 日志级别

- ERROR: 错误信息
- WARNING: 警告信息
- INFO: 一般信息
- DEBUG: 调试信息（开发时使用）

### 关键日志点

- 命令执行开始和结束
- Agent执行状态
- 错误和异常
- Web服务器启动

## 故障排除

### 常见问题

1. **API密钥未设置**: 检查 `.env` 文件
2. **命令执行失败**: 检查Kali Linux环境
3. **Token超出限制**: 调整 `max_tokens` 配置
4. **前端无法访问**: 检查前端构建和静态文件路径

### 调试技巧

1. 设置 `LOG_LEVEL=DEBUG`
2. 查看终端输出
3. 检查Web API响应
4. 使用 `/api/memory/stats` 查看记忆状态
