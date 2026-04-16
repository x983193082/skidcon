# SkidCon 渗透测试能力优化方案

> 生成时间：2026-04-16
> 项目版本：1.0.0
> 状态：待实施

---

## 一、当前架构概述

### 1.1 整体架构

```
┌─────────────────────────────────────────────────────┐
│                  前端 (Vue 3 + Vite)                 │
│  App.vue ── api.js (REST) ── ws.js (WebSocket)      │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP + WebSocket
┌──────────────────────▼──────────────────────────────┐
│              后端 (FastAPI + Uvicorn)                │
│  main.py ── task_manager.py ── crew_runner.py       │
│         ── agents.py ── tools.py ── report.py       │
└──────────────────────┬──────────────────────────────┘
                       │ 子进程调用
┌──────────────────────▼──────────────────────────────┐
│              Kali Linux 工具 (50+)                   │
│  nmap, sqlmap, nuclei, metasploit, hydra, ...       │
└─────────────────────────────────────────────────────┘
```

### 1.2 核心模块

| 模块 | 文件 | 职责 |
|------|------|------|
| **API 层** | `main.py` | FastAPI 入口，REST API + WebSocket |
| **任务管理** | `task_manager.py` | 并发控制、任务生命周期、持久化 |
| **执行引擎** | `crew_runner.py` | 5 阶段链式攻击流程 |
| **智能体** | `agents.py` | 4 个 Agent（Planner/Executor/Analyzer/Reporter） |
| **工具封装** | `tools.py` | 35 个工具类，统一异步执行接口 |
| **报告生成** | `report.py` | Markdown 报告模板 |
| **配置** | `config.py` | API 密钥、工具路径、超时设置 |

### 1.3 当前工作流

```
阶段1: 信息收集 → nmap + subfinder + whatweb + whois + dig
       ↓
阶段2: 服务分析 → nikto + enum4linux + smbclient
       ↓
阶段3: 漏洞检测 → sqlmap + nuclei + searchsploit
       ↓
阶段4: 漏洞利用 → ⚠️ 空实现（仅模拟）
       ↓
阶段5: 报告生成 → AI 生成 Markdown 报告
```

---

## 二、当前能力与局限性

### 2.1 已实现的能力 ✅

1. **多智能体协作**：4 个专业 Agent 各司其职
2. **工具覆盖广**：配置中定义了 50+ 工具路径，实现了 35 个工具类
3. **异步架构**：FastAPI + asyncio 非阻塞执行
4. **实时推送**：WebSocket 实时推送日志
5. **任务持久化**：JSON 文件存储，支持历史回溯
6. **自动报告**：AI 生成结构化 Markdown 报告

### 2.2 关键局限性 ❌

#### 🔴 严重问题

| # | 问题 | 影响 |
|---|------|------|
| 1 | **攻击流程硬编码** | 不根据发现结果动态调整，Web/内网/云都执行相同工具链 |
| 2 | **Planner 分析不反馈** | 规划 Agent 的分析结果仅用于报告，不指导后续执行 |
| 3 | **漏洞利用阶段为空** | 阶段 4 完全不执行任何操作，Metasploit 从未调用 |
| 4 | **工具参数粗糙** | SQLMap 固定 level=3，Nuclei 只扫 CVE，Gobuster 无字典 |
| 5 | **输出解析薄弱** | 大部分工具只返回 raw_output，无法被 AI 有效利用 |
| 6 | **工具串行执行** | 5 个工具依次执行，总耗时 = 各工具耗时之和 |
| 7 | **无工具可用性检查** | 工具不存在时直接报错，无降级机制 |
| 8 | **命令注入风险** | `format(**kwargs)` 未做参数转义 |
| 9 | **无认证/授权** | 任何人都可以发起渗透测试 |
| 10 | **前端功能简陋** | 无任务暂停/取消、无扫描配置、Markdown 渲染简单 |

#### 🟡 中等问题

| # | 问题 | 影响 |
|---|------|------|
| 11 | **字典文件过小** | directories.txt 仅 35 行，subdomains.txt 仅 40 行 |
| 12 | **无结果缓存** | 重复扫描同一目标浪费资源 |
| 13 | **错误处理不足** | 工具失败不重试，CrewAI 调用失败无回退 |
| 14 | **CORS 配置宽松** | `allow_origins=["*"]` 生产环境不安全 |

---

## 三、优化方案（按优先级排序）

### 🔴 P0 - 关键优化（必须立即实施）

#### 1. 实现动态攻击链引擎

**问题**：当前流程是线性的，不根据发现结果调整策略。

**方案**：新增 `AttackChainEngine` 类，根据扫描到的服务动态选择工具。

```python
class AttackChainEngine:
    """根据发现的服务动态选择工具"""
    
    SERVICE_TOOL_MAP = {
        "http": ["nikto", "sqlmap", "gobuster", "nuclei"],
        "https": ["nikto", "sqlmap", "gobuster", "nuclei"],
        "ssh": ["hydra", "nmap-ssh-audit"],
        "smb": ["enum4linux", "smbclient", "crackmapexec"],
        "ftp": ["hydra", "nmap-ftp-enum"],
        "mysql": ["hydra", "nmap-mysql-enum", "sqlmap"],
        "postgresql": ["hydra", "nmap-pgsql-enum"],
        "smtp": ["nmap-smtp-enum", "hydra"],
        "dns": ["dnsrecon", "dnsenum", "subfinder"],
        "snmp": ["snmpwalk", "onesixtyone"],
        "rdp": ["hydra", "nmap-rdp-enum"],
        "mongodb": ["nmap-mongodb-enum"],
        "redis": ["redis-cli"],
    }
    
    def select_tools(self, recon_results: Dict) -> List[Tuple[str, Dict]]:
        """根据侦察结果选择工具"""
        tools = []
        ports = recon_results.get("nmap", {}).get("parsed_data", {}).get("ports", [])
        
        for port_info in ports:
            service = port_info.get("service", "").lower()
            if service in self.SERVICE_TOOL_MAP:
                for tool_name in self.SERVICE_TOOL_MAP[service]:
                    tools.append((tool_name, self._build_params(tool_name, port_info)))
        
        return tools
```

**预期效果**：
- 扫描 Web 目标时自动聚焦 Web 漏洞工具
- 扫描内网目标时自动启用 SMB/SSH 枚举
- 减少无效工具调用，提高扫描效率

---

#### 2. 完善工具输出解析

**问题**：大部分工具只返回原始输出，无法被 AI 有效利用。

**方案**：为关键工具实现结构化解析，使用 XML/JSON 格式输出。

```python
class NmapTool(KaliTool):
    def __init__(self):
        super().__init__("nmap", "nmap -sV -sC -O -oX - {target}")
    
    def parse_output(self, stdout, stderr):
        """解析 Nmap XML 输出"""
        import xml.etree.ElementTree as ET
        try:
            root = ET.fromstring(stdout)
            ports = []
            for host in root.findall('.//host'):
                ip = host.find('address').get('addr')
                for port_elem in host.findall('.//port'):
                    port_id = port_elem.get('portid')
                    protocol = port_elem.get('protocol')
                    state = port_elem.find('state').get('state')
                    service = port_elem.find('service')
                    ports.append({
                        "ip": ip,
                        "port": f"{port_id}/{protocol}",
                        "state": state,
                        "service": service.get('name') if service else "unknown",
                        "version": service.get('version', '') if service else "",
                        "product": service.get('product', '') if service else "",
                    })
            return {"ports": ports, "hosts": len(root.findall('.//host'))}
        except ET.ParseError:
            return {"ports": [], "raw_output": stdout}


class NucleiTool(KaliTool):
    def __init__(self):
        super().__init__("nuclei", "nuclei -u {url} -json -o /dev/stdout {templates}")
    
    def parse_output(self, stdout, stderr):
        """解析 Nuclei JSON 输出"""
        vulns = []
        for line in stdout.strip().split('\n'):
            if line:
                try:
                    vuln = json.loads(line)
                    vulns.append({
                        "template": vuln.get("template-id", ""),
                        "name": vuln.get("info", {}).get("name", ""),
                        "severity": vuln.get("info", {}).get("severity", ""),
                        "url": vuln.get("matched-at", ""),
                        "cve": vuln.get("info", {}).get("classification", {}).get("cve-id", []),
                    })
                except json.JSONDecodeError:
                    continue
        return {"vulnerabilities": vulns, "count": len(vulns)}
```

**预期效果**：
- AI 能直接读取结构化数据，提高分析准确性
- 减少 token 消耗（不需要传递大量原始输出）
- 便于前端展示结构化结果

---

#### 3. 实现漏洞利用阶段

**问题**：阶段 4 完全为空实现。

**方案**：实现安全的模拟利用 + 可选的实际利用（需授权）。

```python
async def _stage_exploitation(self) -> Dict:
    """漏洞利用阶段"""
    results = {}
    vuln_data = self.stage_results.get("vulnerability_detection", {})
    
    # 1. 从漏洞检测结果中提取可利用的漏洞
    exploitable_vulns = self._identify_exploitable_vulns(vuln_data)
    
    for vuln in exploitable_vulns:
        await self._send_callback(f"  分析漏洞利用方案: {vuln['name']}")
        
        # 2. 搜索对应的 exploit
        if vuln.get("cve_id"):
            exploit_result = await execute_tool(
                "searchsploit", 
                callback=self._send_callback,
                query=vuln["cve_id"]
            )
            results[f"exploit_search_{vuln['cve_id']}"] = exploit_result.parsed_data
        
        # 3. 生成利用方案
        exploit_plan = await self._generate_exploit_plan(vuln)
        results[f"exploit_plan_{vuln['name']}"] = exploit_plan
        
        # 4. 可选：使用 Metasploit 验证（需配置）
        if self.config.get("allow_exploitation", False):
            msf_result = await self._msf_exploit(vuln)
            results[f"msf_exploit_{vuln['name']}"] = msf_result
    
    return results
```

**预期效果**：
- 自动搜索 CVE 对应的 exploit
- 生成详细的利用方案（不实际执行）
- 可选启用实际利用验证（需明确授权）

---

#### 4. 添加工具可用性检查

**方案**：启动时检查所有工具是否可用，标记不可用工具。

```python
import shutil

def check_tool_available(tool_name: str) -> bool:
    """检查工具是否可用"""
    return shutil.which(tool_name) is not None

async def validate_tools() -> Dict[str, bool]:
    """验证所有工具可用性"""
    results = {}
    for tool_name in get_all_tools():
        results[tool_name] = check_tool_available(tool_name)
    return results

# 在 main.py 启动时检查
@app.on_event("startup")
async def startup():
    tool_status = await validate_tools()
    unavailable = [k for k, v in tool_status.items() if not v]
    if unavailable:
        print(f"⚠️ 以下工具不可用: {', '.join(unavailable)}")
```

**预期效果**：
- 启动时明确告知用户哪些工具缺失
- 避免运行时因工具不存在而报错
- 可引导用户安装缺失工具

---

#### 5. 并行执行工具

**问题**：当前工具串行执行，效率低下。

**方案**：使用 `asyncio.gather` 并行执行独立工具。

```python
async def _stage_recon(self) -> Dict:
    """并行信息收集"""
    results = {}
    
    tool_tasks = [
        ("nmap", {"target": target, "port": port}),
        ("subfinder", {"domain": target}),
        ("whatweb", {"url": f"http://{self.target}"}),
        ("whois", {"domain": target}),
        ("dig", {"domain": target}),
    ]
    
    async def run_tool(name, kwargs):
        result = await execute_tool(name, callback=self._send_callback, **kwargs)
        return name, result
    
    tasks = [run_tool(name, kwargs) for name, kwargs in tool_tasks]
    completed = await asyncio.gather(*tasks, return_exceptions=True)
    
    for item in completed:
        if isinstance(item, Exception):
            await self._send_callback(f"  ⚠️ 工具执行异常: {item}")
            continue
        name, result = item
        if result:
            results[name] = {
                "success": result.success,
                "parsed_data": result.parsed_data,
                "raw_output": result.stdout[:2000]
            }
    
    return results
```

**预期效果**：
- 信息收集阶段耗时从 5 个工具之和 → 最慢工具的耗时
- 整体扫描时间减少 50-70%

---

### 🟡 P1 - 重要优化（建议尽快实施）

#### 6. 增强 Agent 工具调用能力

**方案**：赋予 Agent 直接调用工具的能力，而非硬编码工具链。

```python
from crewai_tools import BaseTool

class ToolExecutionTool(BaseTool):
    """允许 Agent 直接调用工具"""
    name: str = "execute_pentest_tool"
    description: str = "执行渗透测试工具"
    
    def _run(self, tool_name: str, **kwargs) -> str:
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(
            execute_tool(tool_name, **kwargs)
        )
        return result.stdout if result else "工具执行失败"

def create_executor_agent() -> Agent:
    return Agent(
        role="工具执行专家",
        goal="精确执行各类渗透测试工具",
        backstory="...",
        llm=MODEL_NAME,
        verbose=True,
        allow_delegation=False,
        tools=[ToolExecutionTool()]  # 赋予工具调用能力
    )
```

**预期效果**：
- Agent 可根据上下文自主决定调用哪些工具
- 更灵活的渗透测试流程
- 更接近人类专家的工作方式

---

#### 7. 改进报告生成

**方案**：增强报告结构，添加攻击路径、风险矩阵等内容。

```markdown
# SkidCon 渗透测试报告

## 基本信息
- 目标：xxx
- 时间：xxx
- 测试类型：黑盒/白盒/灰盒

## 1. 执行摘要
- 发现漏洞总数
- 风险等级分布
- 关键发现

## 2. 攻击面分析
### 2.1 网络拓扑
### 2.2 开放服务
### 2.3 技术栈识别

## 3. 漏洞详情
### 3.1 Critical 漏洞
### 3.2 High 漏洞
### 3.3 Medium 漏洞
### 3.4 Low/Info 漏洞

## 4. 攻击路径
### 4.1 可能的攻击链
### 4.2 利用难度评估

## 5. 修复建议
### 5.1 紧急修复（Critical/High）
### 5.2 计划修复（Medium）
### 5.3 建议改进（Low/Info）

## 6. 附录
### 6.1 工具输出
### 6.2 参考资料
```

---

#### 8. 前端改进

| 功能 | 描述 | 优先级 |
|------|------|--------|
| **Markdown 渲染** | 集成 marked.js + highlight.js 替代正则渲染 | P1 |
| **任务控制** | 添加暂停/取消/重试按钮 | P1 |
| **扫描配置** | 选择工具、调整深度、设置速度 | P1 |
| **报告对比** | 选择两个任务对比差异 | P2 |
| **仪表盘** | 显示统计图表（漏洞分布、趋势） | P2 |
| **实时拓扑** | 可视化展示发现的资产和漏洞 | P2 |

---

#### 9. 添加工具错误重试和降级

```python
async def execute_with_retry(self, callback=None, max_retries=2, **kwargs) -> ToolResult:
    """带重试的工具执行"""
    for attempt in range(max_retries + 1):
        result = await self.execute(callback, **kwargs)
        if result.success:
            return result
        
        if attempt < max_retries:
            await asyncio.sleep(2 ** attempt)  # 指数退避
            if callback:
                await callback(f"[{self.tool_name}] 执行失败，重试 ({attempt + 1}/{max_retries})")
    
    return result
```

---

### 🟢 P2 - 增强优化（建议后续实施）

#### 10. 添加缺失的重要工具

| 工具 | 类别 | 用途 | 优先级 |
|------|------|------|--------|
| **CrackMapExec** | 内网渗透 | SMB/WinRM/SSH 批量枚举 | 🔴 |
| **Hydra** | 密码攻击 | 多协议密码爆破 | 🔴 |
| **Commix** | Web 攻击 | 命令注入检测 | 🔴 |
| **XSSer** | Web 攻击 | XSS 漏洞检测 | 🟡 |
| **Burp Suite** | Web 扫描 | 专业 Web 漏洞扫描 | 🟡 |
| **ZAP** | Web 扫描 | OWASP ZAP 自动化扫描 | 🟡 |
| **Responder** | 内网攻击 | LLMNR/NBT-NS 欺骗 | 🟡 |
| **Impacket** | 协议攻击 | SMB/DCERPC/Kerberos 协议利用 | 🟡 |
| **BloodHound** | AD 攻击 | Active Directory 攻击路径分析 | 🟢 |
| **Evil-WinRM** | 后渗透 | Windows 远程管理 | 🟢 |

---

#### 11. 扩展字典文件

**directories.txt** 应包含：
- 常见管理后台路径（admin, login, dashboard）
- API 端点（api, v1, v2, graphql, swagger）
- 敏感文件（.env, .git, config.php, wp-config.php）
- CMS 路径（wp-admin, phpmyadmin, adminer）
- 调试接口（debug, console, phpinfo, health）
- 云原生路径（docker, kubernetes, prometheus, grafana）

**subdomains.txt** 应包含：
- 常见子域名（www, mail, ftp, admin, api, dev, test, staging）
- 云服务子域名（s3, cdn, storage, db, cache）
- 内部服务子域名（internal, intranet, vpn, jenkins, gitlab）

---

#### 12. 添加结果缓存

```python
import hashlib
import json

class ScanCache:
    """扫描结果缓存"""
    
    def __init__(self, cache_dir="data/cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_cache_key(self, target: str, tool: str) -> str:
        """生成缓存键"""
        raw = f"{target}:{tool}"
        return hashlib.md5(raw.encode()).hexdigest()
    
    def get(self, target: str, tool: str) -> Optional[Dict]:
        """获取缓存结果"""
        key = self._get_cache_key(target, tool)
        cache_file = self.cache_dir / f"{key}.json"
        if cache_file.exists():
            with open(cache_file) as f:
                return json.load(f)
        return None
    
    def set(self, target: str, tool: str, result: Dict, ttl: int = 86400):
        """缓存结果"""
        key = self._get_cache_key(target, tool)
        cache_file = self.cache_dir / f"{key}.json"
        data = {
            "target": target,
            "tool": tool,
            "result": result,
            "timestamp": time.time(),
            "ttl": ttl
        }
        with open(cache_file, 'w') as f:
            json.dump(data, f)
```

---

#### 13. 添加认证和授权

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """验证 API Token"""
    if credentials.credentials != os.getenv("API_TOKEN"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token"
        )
    return True

# 在路由中使用
@app.post("/api/task", dependencies=[Depends(verify_token)])
async def create_task(request: CreateTaskRequest):
    ...
```

---

#### 14. 添加速率限制

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.post("/api/task")
@limiter.limit("5/minute")
async def create_task(request: Request, create_request: CreateTaskRequest):
    ...
```

---

## 四、实施路线图

### 第一阶段（1-2 周）- P0 关键优化

| 任务 | 预计时间 | 依赖 |
|------|----------|------|
| 1. 动态攻击链引擎 | 3 天 | 无 |
| 2. 工具输出解析增强 | 2 天 | 无 |
| 3. 漏洞利用阶段实现 | 3 天 | 2 |
| 4. 工具可用性检查 | 1 天 | 无 |
| 5. 并行执行工具 | 2 天 | 1 |

### 第二阶段（2-3 周）- P1 重要优化

| 任务 | 预计时间 | 依赖 |
|------|----------|------|
| 6. Agent 工具调用能力 | 3 天 | 第一阶段 |
| 7. 报告生成增强 | 2 天 | 2, 3 |
| 8. 前端改进 | 5 天 | 无 |
| 9. 错误重试和降级 | 2 天 | 4 |

### 第三阶段（3-4 周）- P2 增强优化

| 任务 | 预计时间 | 依赖 |
|------|----------|------|
| 10. 添加缺失工具 | 5 天 | 无 |
| 11. 扩展字典文件 | 2 天 | 无 |
| 12. 结果缓存 | 2 天 | 无 |
| 13. 认证和授权 | 2 天 | 无 |
| 14. 速率限制 | 1 天 | 13 |

---

## 五、预期效果

### 5.1 性能提升

| 指标 | 优化前 | 优化后 | 提升 |
|------|--------|--------|------|
| 扫描时间 | 15-30 分钟 | 5-10 分钟 | 50-70% |
| 工具覆盖率 | 35 个 | 50+ 个 | 40%+ |
| 漏洞检出率 | 低（硬编码） | 高（动态） | 显著提升 |
| 误报率 | 高 | 低（结构化分析） | 显著降低 |

### 5.2 功能增强

- ✅ 动态攻击链：根据发现结果自动调整策略
- ✅ 并行执行：大幅缩短扫描时间
- ✅ 结构化输出：AI 分析更准确
- ✅ 漏洞利用：自动搜索 exploit 并生成利用方案
- ✅ 工具检查：启动时明确告知缺失工具
- ✅ 错误重试：提高系统稳定性
- ✅ 认证授权：生产环境安全
- ✅ 前端增强：更好的用户体验

---

## 六、安全注意事项

1. **授权测试**：确保所有渗透测试都经过明确授权
2. **命令注入防护**：对所有工具参数进行转义和验证
3. **速率限制**：防止系统被滥用
4. **日志审计**：记录所有操作以便追溯
5. **数据保护**：敏感信息（API Key、密码）加密存储
6. **隔离环境**：建议在隔离环境中运行，避免影响生产系统

---

## 七、总结

SkidCon 项目已经具备了良好的架构基础，但在**动态决策能力**、**工具执行效率**、**输出解析质量**和**漏洞利用深度**方面还有较大提升空间。

通过实施本优化方案，项目将从一个**线性扫描工具**升级为一个**智能渗透测试平台**，能够：

1. 根据目标特征自动选择最优攻击策略
2. 并行执行工具，大幅缩短扫描时间
3. 结构化分析结果，提高 AI 判断准确性
4. 自动搜索 exploit 并生成详细利用方案
5. 提供更专业、更全面的渗透测试报告

建议按照 **P0 → P1 → P2** 的优先级顺序逐步实施，每个阶段完成后进行充分测试和验证。
