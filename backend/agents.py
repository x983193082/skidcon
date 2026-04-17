"""
SkidCon CrewAI Agent 定义
定义 4 个 Agent：PlannerAgent, ExecutorAgent, AnalyzerAgent, ReporterAgent
支持绑定所有 Kali Linux 安全工具
"""

import subprocess
from crewai import Agent
from crewai.tools import BaseTool
from typing import Optional
from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, MODEL_NAME


# ==================== 通用 Kali 工具执行器 ====================

class ExecuteKaliTool(BaseTool):
    """通用 Kali 工具执行器 - Agent 可通过此工具调用任何已注册的 Kali 工具"""
    name: str = "execute_kali_tool"
    description: str = """执行 Kali Linux 渗透测试工具。
用法: 提供工具名称和参数字典。
可用工具列表:
- 扫描类: nmap, masscan, rustscan, naabu
- Web 类: sqlmap, gobuster, dirb, ffuf, nikto, wpscan, joomscan
- 漏洞利用: searchsploit, nuclei, metasploit
- 信息收集: whois, dig, nslookup, host, theharvester, amass, subfinder, assetfinder, dnsrecon, dnsenum, whatweb
- 服务枚举: enum4linux, smbclient, snmpwalk, onesixtyone
- 密码攻击: hydra, john, hashcat, crunch, cewl
- 后渗透: linpeas, winpeas, linenum, linux-exploit-suggester
- 其他: curl, wget, nc, socat

示例:
- {"tool": "nmap", "args": "-sV -p 80,443 192.168.1.1"}
- {"tool": "curl", "args": "-I http://target.com"}
- {"tool": "nikto", "args": "-h http://target.com"}
- {"tool": "sqlmap", "args": "-u http://target.com/page?id=1 --batch"}
- {"tool": "nuclei", "args": "-u http://target.com"}
- {"tool": "gobuster", "args": "dir -u http://target.com -w /usr/share/wordlists/dirb/common.txt"}
- {"tool": "whois", "args": "target.com"}
- {"tool": "dig", "args": "target.com ANY"}
- {"tool": "searchsploit", "args": "Apache 2.4.33"}
- {"tool": "enum4linux", "args": "192.168.1.1"}
- {"tool": "hydra", "args": "-l admin -P /usr/share/wordlists/rockyou.txt 192.168.1.1 ssh"}
"""
    
    def _run(self, tool_and_args: str) -> str:
        """执行 Kali 工具命令"""
        import json
        import shutil
        
        try:
            # 解析输入：支持 JSON 格式或简单字符串
            tool_and_args = tool_and_args.strip()
            
            if tool_and_args.startswith("{"):
                # JSON 格式: {"tool": "nmap", "args": "-sV target"}
                params = json.loads(tool_and_args)
                tool_name = params.get("tool", "")
                args = params.get("args", "")
            else:
                # 简单格式: nmap -sV target
                parts = tool_and_args.split(None, 1)
                tool_name = parts[0] if parts else ""
                args = parts[1] if len(parts) > 1 else ""
            
            if not tool_name:
                return "错误: 未指定工具名称"
            
            # 安全限制：禁止危险命令
            dangerous = ["rm -rf", "mkfs", "dd if=", "chmod 777 /", "wget http", "curl -o /etc"]
            full_command = f"{tool_name} {args}"
            for d in dangerous:
                if d in full_command.lower():
                    return f"错误: 命令包含不允许的操作"
            
            # 检查工具是否存在
            tool_path = shutil.which(tool_name)
            if not tool_path:
                return f"错误: 工具 '{tool_name}' 未安装或不在 PATH 中"
            
            # 执行命令
            command = f"{tool_path} {args}"
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=180  # 3 分钟超时
            )
            
            output = result.stdout if result.stdout else ""
            if result.stderr:
                output += f"\n[STDERR] {result.stderr}"
            
            # 限制输出长度
            if len(output) > 5000:
                output = output[:5000] + f"\n... [输出已截断，总长度 {len(output)} 字符]"
            
            return output if output else "命令执行成功，无输出"
            
        except json.JSONDecodeError:
            return "错误: 参数格式不正确，请使用 JSON 格式或 '工具名 参数' 格式"
        except subprocess.TimeoutExpired:
            return f"错误: 工具 '{tool_name}' 执行超时 (180s)"
        except Exception as e:
            return f"错误: {str(e)}"


# ==================== 快捷工具（常用工具独立包装） ====================

class CurlTool(BaseTool):
    """Curl HTTP 请求工具 - 快捷方式"""
    name: str = "curl"
    description: str = "发送 HTTP 请求。用法: <url> [options]。示例: http://target.com -I"
    
    def _run(self, args: str) -> str:
        command = f"curl {args.strip()}"
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
            output = result.stdout or ""
            if result.stderr:
                output += f"\n[STDERR] {result.stderr}"
            return output[:3000]
        except subprocess.TimeoutExpired:
            return "错误: 请求超时 (30s)"
        except Exception as e:
            return f"错误: {str(e)}"


class NmapScanTool(BaseTool):
    """Nmap 端口扫描工具 - 快捷方式"""
    name: str = "nmap_scan"
    description: str = "端口扫描和服务识别。用法: <target> [options]。示例: 192.168.1.1 -sV -p 80,443"
    
    def _run(self, args: str) -> str:
        command = f"nmap -sV -sC -oX - {args.strip()}"
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=120)
            output = result.stdout or ""
            if result.stderr:
                output += f"\n[STDERR] {result.stderr}"
            return output[:3000]
        except subprocess.TimeoutExpired:
            return "错误: 扫描超时 (120s)"
        except Exception as e:
            return f"错误: {str(e)}"


# ==================== 工具列表 ====================

# 所有 Agent 可用的工具
ALL_AGENT_TOOLS = [
    ExecuteKaliTool(),  # 通用工具执行器（可调用所有 Kali 工具）
    CurlTool(),         # curl 快捷方式
    NmapScanTool(),     # nmap 快捷方式
]


def get_tools_for_agent(tool_names: Optional[list] = None) -> list:
    """获取指定名称的工具列表"""
    if tool_names is None:
        return ALL_AGENT_TOOLS
    
    return [t for t in ALL_AGENT_TOOLS if t.name in tool_names]


def create_planner_agent() -> Agent:
    """创建规划 Agent（带全部 Kali 工具）"""
    return Agent(
        role="渗透测试规划专家",
        goal="分析目标系统，制定最优的渗透测试攻击路径和策略",
        backstory="""你是一位拥有 15 年经验的资深渗透测试专家，擅长分析目标系统并制定全面的攻击策略。
你熟悉各种渗透测试方法论（如 PTES、OWASP Testing Guide），能够根据目标特征选择最合适的工具和技术。
你的任务是分析目标 IP/URL，识别潜在的攻击面，并制定分阶段的测试计划。
你可以使用 execute_kali_tool 调用任何 Kali 工具（nmap、whois、dig、curl、subfinder 等）来收集目标信息。""",
        llm=MODEL_NAME,
        verbose=True,
        allow_delegation=False,
        tools=ALL_AGENT_TOOLS
    )


def create_executor_agent() -> Agent:
    """创建执行 Agent（带全部 Kali 工具）"""
    return Agent(
        role="工具执行专家",
        goal="精确执行各类渗透测试工具，获取准确的扫描和测试结果",
        backstory="""你是一位精通各类渗透测试工具的安全工程师，熟练使用 Nmap、SQLMap、Metasploit、Burp Suite 等 50+ 安全工具。
你能够根据规划阶段的策略，精确配置和执行工具，获取准确的扫描结果。
你擅长解读工具输出，识别关键信息，并为后续分析阶段提供结构化数据。
你可以使用 execute_kali_tool 调用任何 Kali 工具（nmap、sqlmap、nikto、nuclei、gobuster、hydra 等）进行主动扫描和测试。""",
        llm=MODEL_NAME,
        verbose=True,
        allow_delegation=False,
        tools=ALL_AGENT_TOOLS
    )


def create_analyzer_agent() -> Agent:
    """创建分析 Agent（带全部 Kali 工具）"""
    return Agent(
        role="漏洞分析专家",
        goal="分析执行结果，识别真实漏洞，降低误报率，评估风险等级",
        backstory="""你是一位经验丰富的漏洞研究员，拥有 CVE 编号分配权限。
你擅长分析各种安全工具的输出结果，区分真实漏洞和误报。
你能够根据 CVSS 评分标准评估漏洞风险等级，并提供详细的漏洞描述和利用场景分析。
你的分析结果将直接用于生成最终的安全报告。
你可以使用 execute_kali_tool 调用 searchsploit、nuclei 等工具进行漏洞验证。""",
        llm=MODEL_NAME,
        verbose=True,
        allow_delegation=False,
        tools=ALL_AGENT_TOOLS
    )


def create_reporter_agent() -> Agent:
    """创建报告 Agent（带全部 Kali 工具）"""
    return Agent(
        role="报告生成专家",
        goal="生成详细专业的渗透测试报告，提供可操作的修复建议",
        backstory="""你是一位专业的安全咨询顾问，擅长撰写高质量的渗透测试报告。
你的报告结构清晰、内容详实，包含执行摘要、漏洞详情、风险评级、修复建议等关键部分。
你能够用通俗易懂的语言解释技术漏洞，帮助客户理解安全风险并采取有效的修复措施。
你的报告符合行业标准（如 PTES、NIST SP 800-115）。
你可以使用 execute_kali_tool 调用 curl 等工具验证修复建议。""",
        llm=MODEL_NAME,
        verbose=True,
        allow_delegation=False,
        tools=ALL_AGENT_TOOLS
    )


def create_analyzer_agent() -> Agent:
    """创建分析 Agent"""
    return Agent(
        role="漏洞分析专家",
        goal="分析执行结果，识别真实漏洞，降低误报率，评估风险等级",
        backstory="""你是一位经验丰富的漏洞研究员，拥有 CVE 编号分配权限。
你擅长分析各种安全工具的输出结果，区分真实漏洞和误报。
你能够根据 CVSS 评分标准评估漏洞风险等级，并提供详细的漏洞描述和利用场景分析。
你的分析结果将直接用于生成最终的安全报告。""",
        llm=MODEL_NAME,
        verbose=True,
        allow_delegation=False
    )


def create_reporter_agent() -> Agent:
    """创建报告 Agent"""
    return Agent(
        role="报告生成专家",
        goal="生成详细专业的渗透测试报告，提供可操作的修复建议",
        backstory="""你是一位专业的安全咨询顾问，擅长撰写高质量的渗透测试报告。
你的报告结构清晰、内容详实，包含执行摘要、漏洞详情、风险评级、修复建议等关键部分。
你能够用通俗易懂的语言解释技术漏洞，帮助客户理解安全风险并采取有效的修复措施。
你的报告符合行业标准（如 PTES、NIST SP 800-115）。""",
        llm=MODEL_NAME,
        verbose=True,
        allow_delegation=False
    )


# Agent 工厂字典
AGENT_FACTORIES = {
    "planner": create_planner_agent,
    "executor": create_executor_agent,
    "analyzer": create_analyzer_agent,
    "reporter": create_reporter_agent,
}


def get_agent(agent_type: str) -> Agent:
    """获取指定类型的 Agent"""
    if agent_type in AGENT_FACTORIES:
        return AGENT_FACTORIES[agent_type]()
    raise ValueError(f"未知的 Agent 类型: {agent_type}")


def get_all_agents() -> dict:
    """获取所有 Agent"""
    return {
        "planner": create_planner_agent(),
        "executor": create_executor_agent(),
        "analyzer": create_analyzer_agent(),
        "reporter": create_reporter_agent()
    }
