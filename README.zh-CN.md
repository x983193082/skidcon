<div align="center">

**[🇨🇳 中文](README.zh-CN.md)** | **[🇬🇧 English](README.md)**

# Skidc

### 多智能体自动化渗透测试平台

*定义**起点**和**目标**，Skidc 即编排大语言模型驱动的智能体，*
*自主规划、执行并验证渗透测试工作流——覆盖 Web、API 与 Android 目标。*

</div>

---

## 什么是 Skidc？

Skidc 是一个自动化渗透测试平台，利用多个大语言模型驱动的智能体贯穿渗透测试全生命周期——
从信息收集到漏洞利用——无需手动编写逐步脚本。

你只需描述**起点**（目标 IP、URL、APK 或域名）和**成功标准**（获取 shell、拿到 flag、
发现 IDOR 等）。Skidc 的调度器将问题拆解为并行探索任务，在隔离的 Docker 容器中执行，
并将每条确认的发现写回共享任务图谱，驱动下一轮推理。

### 核心能力

| 能力 | 说明 |
|------------|-------------|
| **分阶段渗透与门控** | RECON → Explore 阶段切换由项目的 `recon_profile` 驱动，域名、IP、API、Android、混合目标可使用不同的必需证据 |
| **Android MCP 桥接** | 18 个 HTTP 端点用于移动应用控制——UI 交互、截图、网络抓包——无缝集成到渗透测试流程 |
| **事实-意图任务图谱** | 每条确认的发现（fact）和探索方向（intent）均被追踪、可视化，并驱动下一轮推理 |
| **攻击路径标注** | 自动识别利用链并评估严重程度（严重 / 高 / 中 / 低） |
| **可插拔 LLM 后端** | 在 DeepSeek、Qwen、Claude 或任意兼容模型间自由切换——智能体 CLI 与 LLM 完全解耦 |
| **两阶段总结** | 超时不丢进度——恢复同一智能体会话以收集部分结果 |

---

## 工作原理

### 架构

```
              ┌────────────────────────────────────┐
              │           Skidc Server             │   真实数据源：
              │   Facts + Intents + Hints + Paths  │   仅维护图谱一致性
              └─────────────────┬──────────────────┘
                                │  读写协议 API
              ┌─────────────────┴──────────────────┐
              │             Dispatcher             │   唯一协议写入方：
              │  调度 → 认领租约 → 运行 →          │   租约、心跳、超时、
              │  解析 → 写回 → 清理                │   容器生命周期
              └──────────┬───────────────┬─────────┘
                         │               │
              ┌──────────┴─────┐  ┌──────┴───────────┐   每个项目一个容器；
              │ Worker (项目 A) │  │ Worker (项目 B)  │   智能体在其中执行，
              │  claude→DeepSeek│  │  codex→Qwen      │   仅通过图谱协调
              └─────────────────┘  └──────────────────┘
```

**Server**（FastAPI + SQLite）维护任务图谱一致性，管理意图认领 / 推理租约状态机。
**Dispatcher** 是唯一写入协议的组件：读取图谱、决定每个项目的任务类型、认领租约、
在项目容器中运行 worker、解析结构化 JSON 结果并写回。

### 三种任务类型

所有任务均由 Docker 容器内的同一通用 worker 执行：

| 任务 | 触发条件 | 作用 | 输出 |
|------|---------|------|------|
| **Bootstrap（引导）** | 项目处于初始状态 | 尝试直接解决整个问题 | Fact + 可能的 Complete |
| **Reason（推理）** | 出现新事实，或无开放意图 | 读取完整图谱：目标达成？下一步探索什么？ | Complete / 新 Intents / 无操作 |
| **Explore（探索）** | 存在未认领的开放意图 | 认领一个意图，执行并报告发现 | 一个 Fact |

`bootstrap` 和 `explore` 均为**两阶段**：如果主尝试超时或返回不可解析的输出，
调度器会以 `conclude` 提示恢复*同一智能体会话*——"停止工作，仅总结你确认的内容"——
从而保留部分进度而非丢弃。

### 分阶段渗透与 RECON 门控

当项目以 `recon` 阶段启动（真实网站模式）时，调度器在允许工作流进入漏洞利用前
强制执行基于 profile 的**门控检查**：

| RECON 类别 | 所需证据 |
|----------------|-------------------|
| 端口扫描 | nmap / naabu 结果，包含开放端口和服务 |
| 子域名 | subfinder / amass / DNS 枚举结果 |
| 目录 | ffuf / gobuster / dirsearch 路径发现 |
| 资产 | katana / 爬虫结果，包含 URL 和 JS 文件 |

只有项目 `recon_profile.required_categories` 中列出的类别必须覆盖，系统才会从 `recon`
阶段转入 `explore` 阶段。例如单 IP 评估可以禁用子域名枚举，Android 评估可以要求
`android_app`、`android_ui`、`mobile_api`，而不是 Web 类别。门控通过后，潜在子目标
（子域名、开放服务、可疑路径）会自动提取并作为新事实写入图谱，调度器重启后不会重复写入同一目标。

---

## 模型非硬编码

worker 的 **`type`** 选择*智能体 CLI 循环*；worker 的 **`env`** 选择背后*实际的 LLM*。
两者解耦，因此你可以自由组合：

| Worker `type` | 驱动的智能体 CLI | 通信端点（通过 env 设置） | 示例模型 |
|---------------|---------------------|------------------------------------|---------------|
| `claudecode`  | `claude`            | `ANTHROPIC_BASE_URL`（兼容 Anthropic） | **DeepSeek**（`https://api.deepseek.com/anthropic`） |
| `codex`       | `codex`             | `CODEX_BASE_URL`（兼容 OpenAI/Responses） | **Qwen**（`https://dashscope.aliyuncs.com/compatible-mode/v1`） |
| `mock`        | 本地脚本            | 无——用于测试的确定性结果 | — |

```yaml
# 通过 Claude Code 智能体循环运行 DeepSeek：
- name: "claudecode_deepseek"
  type: "claudecode"
  env:
    ANTHROPIC_MODEL: "deepseek-v4-flash"
    ANTHROPIC_BASE_URL: "https://api.deepseek.com/anthropic"
    ANTHROPIC_AUTH_TOKEN: "<YOUR_ANTHROPIC_AUTH_TOKEN>"

# 通过 Codex 智能体循环运行 Qwen：
- name: "codex_qwen"
  type: "codex"
  env:
    CODEX_MODEL: "qwen3.7-plus"
    CODEX_BASE_URL: "https://dashscope.aliyuncs.com/compatible-mode/v1"
    OPENAI_API_KEY: "<YOUR_OPENAI_API_KEY>"
```

切换模型只需编辑配置。添加新后端只需在 `workers/adapters/` 中新增一个驱动文件。

---

## Android Docker Lab（WSL2）

Skidc 内置了面向 WSL2 内部 Docker Engine 的 Android 安全测试环境。Android 流程不会
替换 Web 流程：同一条启动命令会同时运行 Web Server、Dispatcher、隔离的 Emulator 和
带认证的 Bridge；Dispatcher 根据项目目标类型决定 worker 获得哪一组 Prompt 和工具。

| 组件 | 作用 |
|------|------|
| `skidc-server` | 前端、项目 API、Fact-Intent 图谱、证据和报告 |
| `skidc-dispatcher` | 选择 Android Prompt，并调度隔离 worker |
| `android-emulator` | 使用 KVM 加速的 Android 11 测试设备 |
| `android-bridge` | 带认证的 ADB、状态观测和受限 APK 静态分析接口 |

### 运行条件

- WSL2 发行版内部已经安装并启动 Docker Engine，且可使用 Docker Compose v2。
- WSL2 中能够看到 `/dev/kvm`；本项目不会在 KVM 不可用时悄悄退回到低速软件模拟。
- WSL2 可见内存至少 14 GiB，Docker 存储至少有 30 GiB 可用空间。
- 本机端口 `8000` 和 `8765` 未被占用，其中 `8765` 只绑定到回环地址。
- 本地 `dispatch.yaml` 中已经填写可用的模型 API Key。该文件不会被 Git 跟踪；
  不要手工填写 Android Bridge Token，脚本会自动生成并以只读 Secret 方式挂载。

### 首次启动

在 WSL2 中进入仓库根目录，按顺序执行：

```bash
# 1. 首次创建本地调度配置，然后把模型占位符替换为真实 API Key。
[ -e dispatch.yaml ] || cp dispatch_android.example.yaml dispatch.yaml
nano dispatch.yaml
# Dispatcher 在 Compose 容器内运行，须在 dispatch.yaml 中设置：
# server: http://skidc-server:8000
# 然后把所选 worker 的模型 API Key 占位符替换为真实值。

# 2. 检查 WSL2、KVM、Docker、内存、磁盘和 Bridge 端口。
./scripts/android-lab.sh doctor

# 3. 从当前已提交代码构建 skidc-app、skidc-worker 和 skidc-android-bridge。
./scripts/android-lab.sh build

# 4. 生成本地 ADB 密钥、Bridge Bearer Token 和 APK 素材目录。
./scripts/android-lab.sh init

# 5. 一次启动 Web Server、Dispatcher、Android Emulator 和 Android Bridge。
./scripts/android-lab.sh up

# 6. 检查状态，直到四个服务均为 Up，两个 Android 服务均为 healthy。
./scripts/android-lab.sh status

# 7. 验证 Server、Bridge 认证、ADB、截图、UI 树和 worker 客户端调用。
./scripts/android-lab.sh smoke
```

首次 `up` 会下载体积较大的 Emulator 镜像。如果镜像仓库连接不稳定，可先单独拉取后重试：

```bash
docker pull us-docker.pkg.dev/android-emulator-268719/images/30-google-x64-no-metrics:30.1.2
```

`smoke` 不会等待尚未启动完成的 Emulator。如果 `status` 显示 `health: starting`，请等到
`healthy` 后再执行一次 `smoke`。

通常运行根目录就是当前仓库。如果从 Git worktree 执行脚本，但要复用另一个目录中的
`dispatch.yaml`、凭据、APK 和已有容器，请在 `init`、`up`、`status`、`smoke`、`down`
之前设置对应的 WSL 绝对路径：

```bash
export ANDROID_LAB_RUNTIME_ROOT=/mnt/d/path/to/skidcon-skidc
```

脚本会检查 Compose 所有权；如果已有的 `skidc-server` 或 `skidc-dispatcher` 属于另一个
运行根目录，脚本会拒绝复用，避免再次出现同名容器冲突。

### 发起 Android 安全评估

1. 把经过授权的 APK 放入运行根目录的素材目录：

   ```bash
   android_runtime_root=${ANDROID_LAB_RUNTIME_ROOT:-"$PWD"}
   cp /mnt/c/path/to/demo.apk "$android_runtime_root/datas/android-artifacts/demo.apk"
   ```

   如果没有设置 `ANDROID_LAB_RUNTIME_ROOT`，这里会自动使用
   `./datas/android-artifacts/`。

2. 打开 <http://127.0.0.1:8000>，点击“新建项目”，选择“真实网站模式”，再把“目标类型”
   设为“Android”。当前 Android 复用带安全边界和 RECON 的项目表单，真正决定路由的是
   `recon_profile.target_type: android`，并不是把 APK 当作网站处理。
3. 填写已授权目标。“初始状态”中的 APK 路径必须使用 Bridge 容器可见路径：

   ```text
   APK: /artifacts/demo.apk
   Package: com.example.demo
   Device: Docker Android Emulator
   Test accounts: user_a / user_b
   Authorization: 仅允许测试该 APK、包名、模拟器和上述账号
   ```

4. 填写评估目标并创建项目。Dispatcher 会选择 Android Prompt，只在该 Android worker
   内配置 Bridge 凭据，然后运行 Fact-Intent 闭环；Web、API、CTF 项目继续使用默认 Prompt，
   不会获得 Android Bridge 凭据。

Android 流程把受限静态分析（`aapt`、`apktool`、`jadx`）和动态观测、受控操作结合起来：
安装并启动应用，读取 Activity 与 UI 状态，采集截图和 Logcat，操作控件，测试移动 API
Behavior，独立 Verify 候选并把证据写入 Fact。静态结果只是线索，必须得到运行时证据后
才能作为已复现发现。

### 常用操作

| 命令 | 作用 |
|------|------|
| `./scripts/android-lab.sh doctor` | 只读检查宿主环境前置条件 |
| `./scripts/android-lab.sh build` | 重新构建 App、worker 和 Bridge 镜像 |
| `./scripts/android-lab.sh init` | 创建缺失的本地凭据和 APK 目录 |
| `./scripts/android-lab.sh up` | 同时启动 Web、Dispatcher、Emulator 和 Bridge |
| `./scripts/android-lab.sh status` | 查看四个服务及其健康状态 |
| `./scripts/android-lab.sh smoke` | 验证带认证的完整控制链路 |
| `./scripts/android-lab.sh down` | 停止 Lab，并保留绑定挂载的项目数据 |

拉取了会影响镜像的代码后重新执行 `build`；正常关闭后直接执行 `up` 即可。`init` 可以重复
执行，但不会覆盖一组已经完整存在的密钥和 Token。

### 端点概览

| 区域 | 端点 |
|------|-----------|
| 设备状态 | `GET /health`, `GET /devices` |
| 应用生命周期 | `POST /app/install`, `/app/start`, `/app/stop`, `/app/clear` |
| 输入控制 | `POST /input/tap`, `/input/text`, `/input/swipe`, `/input/back`, `/input/home`, `/input/key` |
| 观测 | `GET /observe/ui`, `/observe/activity`, `/observe/screenshot`, `POST /observe/logcat` |
| 网络抓包 | `GET /network/history`, `POST /network/events`, `DELETE /network/history` |
| APK 静态分析 | `POST /reverse/analyze`, `GET /reverse/reports`, `DELETE /reverse/reports` |

`/reverse/analyze` 保留受限 ZIP/字符串基线，并在临时工作区中调用 Bridge 镜像内的
`aapt`、`apktool` 和 `jadx`。响应包含 `analysis_level`、各工具的 `tool_runs`、包名与 SDK
信息、Manifest 安全配置、导出组件、Deep Link，以及带相对 `evidence_ref` 的有界
`code_findings`。单个工具失败不会抹掉其他结果，静态发现仍需动态证据确认。

### 配置 Android 目标

使用 `dispatch_android.example.yaml`，或在现有 `dispatch.yaml` 中加入：

```yaml
runtime:
  prompt_group: "default"
  target_prompt_groups:
    android: "android"

android_bridge:
  url: "http://127.0.0.1:8765"
  token_file: "/run/secrets/android_mcp_token"
  worker_token_file: "/run/skidc/android-mcp-token"
  readiness_timeout: 15
```

不要把 token 值写入 `dispatch.yaml`、Prompt 或 worker 环境。`android-lab.sh`
加载 `docker-compose.android.yaml`，把同一 secret 只读挂载给 Dispatcher 与 Bridge；
Dispatcher 仅为 Android 项目写入 worker 内的 `0600` 凭据文件。

当前边界：`/network/history` 保存的是外部代理或 Addon 导入的事件，系统尚不会自动启动
mitmproxy、安装 CA 或处理证书固定；Frida 端点目前提供脚本元数据并保存外部产生的观测，
尚不会自动启动 Frida Server 或注入应用进程。

完整桥接文档请参阅 [ANDROID_MCP.md](ANDROID_MCP.md)。

---

## 项目结构

```
skidc\
├─ skidc\                         # Python 包（uv 项目）
│  ├─ src\skidc\
│  │  ├─ server\                  # FastAPI + SQLite 任务图谱
│  │  │  ├─ db.py  models.py  services.py  app.py
│  │  │  ├─ routers\             # 项目、意图、提示、设置、导出
│  │  │  └─ static\index.html    # 实时图谱仪表板（零依赖）
│  │  ├─ dispatcher\
│  │  │  ├─ config.py            # dispatch.yaml 配置 + 模型切换环境变量
│  │  │  ├─ contracts.py         # 严格 JSON 输出验证
│  │  │  ├─ scheduler\loop.py    # 控制平面 / 决策树
│  │  │  ├─ tasks\               # bootstrap / reason / explore（+ conclude）
│  │  │  ├─ workers\             # 驱动抽象
│  │  │  │  └─ adapters\         #   claudecode, codex, mock
│  │  │  ├─ runtime\             # docker exec、心跳租约、取消
│  │  │  ├─ recon_extractor.py   # RECON 门控检查 + 子目标提取
│  │  │  └─ prompts\             # default\（攻击）+ android\（移动）+ mock\
│  │  ├─ android_mcp\            # Android MCP 桥接（FastAPI + ADB）
│  │  └─ cli.py                  # `skidc serve` / `skidc dispatch` / `skidc android-mcp`
│  └─ tests\                     # 无需 Docker 和 LLM 即可运行
├─ container\                    # Kali worker 镜像（Dockerfile + AGENTS.md）
├─ benchmark\                    # XBOW 基准测试工具
├─ dispatch.example.yaml         # Web/API 渗透测试模板
├─ dispatch_android.example.yaml # Android 渗透测试模板
├─ dispatch_mock.yaml            # 仅 mock 的本地测试配置
├─ Dockerfile                    # 构建 skidc-app（server + dispatcher 镜像）
├─ docker-compose.yaml
├─ ANDROID_MCP.md                # Android 桥接使用指南
└─ README.md
```

---

## 快速开始

### 前置条件

- **操作系统**：Windows 10/11 + WSL2、macOS 或 Linux
- **Docker Engine + Docker Compose v2**。Docker Desktop 不是必需条件；上文 Android
  Docker Lab 面向直接运行在 WSL2 内的 Docker Engine。
- **Python >= 3.12** 和 [uv](https://docs.astral.sh/uv/)——仅在 `uv run skidc serve / dispatch` 时需要；**仅使用 Docker Compose 则不需要**
- Android Lab 还要求 KVM、**WSL2 可见内存至少 14 GiB**、**Docker 存储至少 30 GiB 可用**

### 方式 A — 使用 Docker Compose 运行 Web/API/CTF（无需 Python）

```powershell
# 1. 构建 worker 镜像（Kali + claude-code + codex）。约 5-15 分钟，约 4.6 GB。
docker build -t skidc-worker:latest -f container/Dockerfile container

# 2. 从模板创建调度器配置，然后填入 LLM 密钥。
copy dispatch.example.yaml dispatch.yaml
notepad dispatch.yaml                  # 设置 server: http://skidc-server:8000，并填写模型 API Key

# 3. 构建应用镜像并启动所有服务。
docker compose up -d --build
```

`dispatch.yaml` 已被 git 忽略，应该只保留在本地。如果真实 provider key 曾经被提交或分享过，
请在供应商后台轮换；把仓库里的内容替换成占位符并不会让旧 key 自动失效。

`docker compose up -d --build` 将：
- 从根目录 `Dockerfile` 构建 `skidc-app`（server + dispatcher 镜像）
- 启动 `skidc-server`（端口 8000）和 `skidc-dispatcher`
- 将 `datas/skidc/` 挂载到 server 内的 `/root/.local/share/skidc/`
  （SQLite 数据库存放位置；重启后数据保留）

验证：

```powershell
docker ps --filter "name=skidc" --format "table {{.Names}}\t{{.Status}}"
# 期望: skidc-server (healthy), skidc-dispatcher (Up)

curl http://127.0.0.1:8000/projects
# 期望: []（空项目列表）
```

打开 http://127.0.0.1:8000 查看仪表板。

如果需要同时启动 Web 与 Android 能力，请使用上文完整的
[Android Docker Lab](#android-docker-labwsl2) 操作流程。

### 方式 B — 直接使用 `uv`（开发模式；应用绕过 Docker，worker 仍使用 Docker）

```powershell
# 终端 1：启动 server
cd skidc
uv sync
uv run skidc serve --host 0.0.0.0

# 终端 2：启动 dispatcher
cp dispatch.example.yaml dispatch.yaml
notepad dispatch.yaml
cd skidc
uv run skidc dispatch --config ..\dispatch.yaml

# 仅验证 worker LLM 配置（每个 worker 一次 ping）后退出：
uv run skidc dispatch --config ..\dispatch.yaml --startup-healthcheck-only
```

### 方式 C — 仅测试（无需 Docker，无需 LLM）

```powershell
cd skidc
uv sync --group dev
uv run --group dev pytest
```

驱动**完整流水线**——server 协议、调度器决策树、全部三种任务类型、两阶段 conclude 回退
以及模型切换驱动——均通过 `mock` worker 在进程内完成。

---

## 日常使用

### 创建项目

1. 在浏览器中打开 http://127.0.0.1:8000。
2. 点击 **New Project**，填写：
   - **Origin（起点）**：目标 IP / URL / 域名 / APK 路径
   - **Goal（目标）**：成功条件（如 `获取 root shell`、`发现 IDOR 漏洞`）
   - **Hints（提示）**（可选）：你已知的信息（开放端口、横幅、凭证）
3. 提交。调度器选择 worker、生成容器并启动渗透测试循环。

真实网站项目应在创建时定义安全边界。UI 已提供这些输入栏，同样的结构也可以直接发给 API：

```json
{
  "title": "authorized web assessment",
  "origin": "https://app.example.test",
  "goal": "find authorization flaws within the agreed scope",
  "mode": "real_website",
  "bootstrap_enabled": false,
  "scope_policy": {
    "allowed_targets": ["app.example.test", "api.example.test"],
    "blocked_targets": ["admin.example.test"],
    "allowed_ports": [80, 443],
    "blocked_ports": [22],
    "allowed_paths": ["/app/"],
    "blocked_paths": ["/private/"],
    "support_ports": [3306],
    "allow_subdomains": false,
    "allow_domain_scan": false,
    "rate_limits": {},
    "passive_only": false
  },
  "recon_profile": {
    "target_type": "domain",
    "required_categories": ["port_scan", "subdomain", "directory", "asset"],
    "optional_categories": [],
    "disabled_categories": []
  }
}
```

调度器会把这些约束注入 worker prompt，并在派发前对结构化 intent 做基础检查；
明显越界的目标、被阻塞的端口、以及违反 `passive_only` 的主动动作会被跳过。

### 查看进度

| 想看的内容 | 查看位置 |
|----------------------|---------------|
| 事实/意图图谱增长 | 仪表板（自动刷新） |
| 智能体当前运行内容 | `docker exec <worker-container> ps aux` |
| 任务为何取消 | `docker logs skidc-dispatcher --tail 100` |
| 哪个 LLM 调用失败 | `docker logs skidc-dispatch-proj_xxx` |

### 停止系统

```powershell
# 优雅停止（数据保留）
docker compose down

# 强制停止（丢失进行中的任务）
docker compose down -v
```

### 关闭后重启

```powershell
docker compose up -d
```

无需重新构建——镜像已缓存。仪表板约 10 秒后即可访问。

---

## 切换 LLM 大脑

智能体 CLI 循环与其背后的 LLM 解耦。切换方法：

1. 编辑 `dispatch.yaml`。每个 worker 的 `env:` 块是唯一需要修改的地方。
2. 常见切换：

| 目标 | Worker `type` | 所需环境变量 |
|------|---------------|--------------|
| DeepSeek（Claude Code 循环） | `claudecode` | `ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL`, `ANTHROPIC_AUTH_TOKEN` |
| Qwen（Codex 循环） | `codex` | `CODEX_BASE_URL`, `CODEX_MODEL`, `OPENAI_API_KEY` |
| Anthropic Claude（官方） | `claudecode` | `ANTHROPIC_BASE_URL=https://api.anthropic.com`, `ANTHROPIC_MODEL=claude-sonnet-4-5`, `ANTHROPIC_AUTH_TOKEN=<YOUR_ANTHROPIC_AUTH_TOKEN>` |

3. 重启 dispatcher——无需重新构建：

```powershell
docker compose restart skidc-dispatcher
```

---

## 故障排查

### Worker 容器以退出码 137 退出

退出码 137 = SIGKILL = OOM 杀手。修复：在 `dispatch.yaml` 中硬限制 worker 容器内存：

```yaml
container:
  image: "skidc-worker:latest"
  network_mode: "host"
  completed_action: "remove"
  mem_limit: "3g"
```

### `docker exec` 报错 "cannot be used with root/sudo privileges"

Claude Code 在 root 模式下拒绝 `--dangerously-skip-permissions`。确认
`container/Dockerfile` 包含：

```dockerfile
RUN useradd -m -s /bin/bash kali && \
    echo "kali ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers
USER kali
```

### ghcr.io 超时 / 404

中国网络常见问题。改用 Docker Hub 基础镜像：

```dockerfile
FROM python:3.13-slim-bookworm
RUN pip install uv
```

### Kali apt 镜像失败（403）

在 `container/Dockerfile` 中将 `mirror.wane.kr` 替换为 `mirrors.aliyun.com`。

---

## 合规使用

Skidc 面向已授权的渗透测试 / CTF / 安全评估环境。**仅**在你拥有明确操作授权的情况下使用。
未经授权的安全测试可能违法且有害。你对本项目的使用方式承担全部责任。
