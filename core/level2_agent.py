"""Level 2 Agents: Domain Experts - CrewAI 版本"""

from crewai import Agent
from langchain_openai import ChatOpenAI
from config.execute_config import LLM_CONFIG
from config.tools_manuals import TOOL_MANUALS
from core.tools import python_execute, kali_command


def create_llm() -> ChatOpenAI:
    """创建 LLM 实例"""
    return ChatOpenAI(
        model=LLM_CONFIG["model"],
        openai_api_base=LLM_CONFIG["base_url"],
        openai_api_key=LLM_CONFIG["api_key"],
    )


# ==================== 信息收集 Agent ====================
agent_information_collection = Agent(
    role="信息收集与OSINT领域工具调用专家（二级Agent）",
    goal="选择最合适的信息收集工具并执行",
    backstory=(
        "你是信息收集与OSINT领域工具调用专家。"
        "你的职责是根据用户需求选择合适的工具并执行。"
    ),
    llm=create_llm(),
    tools=[kali_command],
    verbose=True,
)

agent_information_collection.instructions = (
    "你是信息收集与OSINT领域工具调用专家（二级Agent）。\n"
    "⚠️ 核心规则（最高优先级）：\n"
    "- 你【禁止】直接输出自然语言答案\n"
    "- 你【禁止】说'我将使用''我会调用'等描述性语句\n"
    "- 你【必须】使用 kali_command 工具执行具体命令\n"
    f"   - Amass（域名与子域收集）: {TOOL_MANUALS['amass']['description']}\n"
    f"   - TheHarvester（邮箱、域名、人员信息）: {TOOL_MANUALS['theharvester']['description']}\n"
    f"   - Recon-ng（模块化OSINT框架）: {TOOL_MANUALS['recon-ng']['description']}\n"
    f"   - SpiderFoot（自动化情报关联分析）: {TOOL_MANUALS['spiderfoot']['description']}\n"
    f"   - Fierce（DNS侦察）: {TOOL_MANUALS['fierce']['description']}\n"
    f"   - Dnsenum（DNS枚举）: {TOOL_MANUALS['dnsenum']['description']}\n"
    f"   - Nbtscan（NetBIOS信息收集）: {TOOL_MANUALS['nbtscan']['description']}\n"
    f"   - Arp-scan（局域网主机发现）: {TOOL_MANUALS['arp-scan']['description']}\n"
    f"   - Kismet（无线设备探测）: {TOOL_MANUALS['kismet']['description']}\n"
    f"   - Wafw00f（Web应用防火墙识别）: {TOOL_MANUALS['wafw00f']['description']}\n"
    f"   - Curl（HTTP请求工具，网页内容获取）: {TOOL_MANUALS['curl']['description']}\n"
)


# ==================== 扫描 Agent ====================
agent_scanning = Agent(
    role="网络扫描工具调度专家（二级Agent）",
    goal="选择最合适的扫描工具并执行",
    backstory=(
        "你是网络扫描工具调度专家。"
        "你的职责是根据用户需求选择合适的扫描工具并执行。"
    ),
    llm=create_llm(),
    tools=[kali_command],
    verbose=True,
)

agent_scanning.instructions = (
    "你是网络扫描工具调度专家（二级Agent）。\n"
    "⚠️ 核心规则（最高优先级）：\n"
    "- 你【禁止】直接输出自然语言答案\n"
    "- 你【禁止】说'我将使用''我会调用'等描述性语句\n"
    "- 你【必须】使用 kali_command 工具执行具体命令\n"
    f"   - Nmap（端口与服务识别）: {TOOL_MANUALS['nmap']['description']}\n"
    f"   - Masscan（高速端口扫描）: {TOOL_MANUALS['masscan']['description']}\n"
    f"   - Tcpdump（原始流量捕获）: {TOOL_MANUALS['tcpdump']['description']}\n"
    f"   - Tshark（命令行流量分析）: {TOOL_MANUALS['tshark']['description']}\n"
    f"   - Wireshark（图形化流量分析）: {TOOL_MANUALS['wireshark']['description']}\n"
    f"   - Httpx（Web服务探测）: {TOOL_MANUALS['httpx']['description']}\n"
    f"   - Curl（HTTP响应验证）: {TOOL_MANUALS['curl']['description']}\n"
    f"   - Gobuster（目录/子域爆破）: {TOOL_MANUALS['gobuster']['description']}\n"
)


# ==================== 枚举 Agent ====================
agent_enumeration = Agent(
    role="服务枚举与攻击面扩展工具调用专家（二级Agent）",
    goal="选择最合适的枚举工具并执行",
    backstory=(
        "你是服务枚举与攻击面扩展工具调用专家。"
        "你的职责是根据用户需求选择合适的枚举工具并执行。"
    ),
    llm=create_llm(),
    tools=[kali_command],
    verbose=True,
)

agent_enumeration.instructions = (
    "你是服务枚举与攻击面扩展工具调用专家（二级Agent）。\n"
    "⚠️ 核心规则（最高优先级）：\n"
    "- 你【禁止】直接输出自然语言答案\n"
    "- 你【禁止】说'我将使用''我会调用'等描述性语句\n"
    "- 你【必须】使用 kali_command 工具执行具体命令\n"
    f"   - Enum4linux（SMB 枚举）: {TOOL_MANUALS['enum4linux']['description']}\n"
    f"   - Rpcclient（RPC 服务枚举）: {TOOL_MANUALS['rpcclient']['description']}\n"
    f"   - Smbmap（共享与权限枚举）: {TOOL_MANUALS['smbmap']['description']}\n"
    f"   - Dirb（Web 目录枚举）: {TOOL_MANUALS['dirb']['description']}\n"
    f"   - Gobuster（目录/子域爆破）: {TOOL_MANUALS['gobuster']['description']}\n"
    f"   - FFUF（参数/路径模糊测试）: {TOOL_MANUALS['ffuf']['description']}\n"
    f"   - Wfuzz（Web 接口枚举）: {TOOL_MANUALS['wfuzz']['description']}\n"
    f"   - Nikto（Web 配置与漏洞枚举）: {TOOL_MANUALS['nikto']['description']}\n"
    f"   - WPScan（WordPress 枚举）: {TOOL_MANUALS['wpscan']['description']}\n"
    f"   - NXC（网络协议枚举）: {TOOL_MANUALS['nxc']['description']}\n"
    f"   - Curl（HTTP响应验证）: {TOOL_MANUALS['curl']['description']}\n"
)


# ==================== Web 利用 Agent ====================
agent_web_exploitation = Agent(
    role="Web漏洞利用工具调用专家（二级Agent）",
    goal="选择最合适的Web漏洞利用工具并执行",
    backstory=(
        "你是Web漏洞利用工具调用专家。"
        "你的职责是根据用户需求选择合适的Web漏洞利用工具并执行。"
    ),
    llm=create_llm(),
    tools=[kali_command],
    verbose=True,
)

agent_web_exploitation.instructions = (
    "你是Web漏洞利用工具调用专家（二级Agent）。\n"
    "⚠️ 核心规则（最高优先级）：\n"
    "- 你【禁止】直接输出自然语言答案\n"
    "- 你【禁止】说'我将使用''我会调用'等描述性语句\n"
    "- 你【必须】使用 kali_command 工具执行具体命令\n"
    f"   - SQLMap（SQL注入）: {TOOL_MANUALS['sqlmap']['description']}\n"
    f"   - Nikto（Web漏洞扫描）: {TOOL_MANUALS['nikto']['description']}\n"
    f"   - Wfuzz（参数与接口 fuzz）: {TOOL_MANUALS['wfuzz']['description']}\n"
    f"   - FFUF（路径与参数爆破）: {TOOL_MANUALS['ffuf']['description']}\n"
    f"   - Gobuster（Web 枚举辅助）: {TOOL_MANUALS['gobuster']['description']}\n"
    f"   - WPScan（WordPress 漏洞）: {TOOL_MANUALS['wpscan']['description']}\n"
    f"   - Curl（HTTP请求工具，网页内容获取）: {TOOL_MANUALS['curl']['description']}\n"
)


# ==================== 漏洞利用 Agent ====================
agent_exploitation = Agent(
    role="漏洞利用与初始控制工具调用专家（二级Agent）",
    goal="选择最合适的漏洞利用工具并执行",
    backstory=(
        "你是漏洞利用与初始控制工具调用专家。"
        "你的职责是根据用户需求选择合适的漏洞利用工具并执行。"
    ),
    llm=create_llm(),
    tools=[kali_command],
    verbose=True,
)

agent_exploitation.instructions = (
    "你是漏洞利用与初始控制工具调用专家（二级Agent）。\n"
    "⚠️ 核心规则（最高优先级）：\n"
    "- 你【禁止】直接输出自然语言答案\n"
    "- 你【禁止】说'我将使用''我会调用'等描述性语句\n"
    "- 你【必须】使用 kali_command 工具执行具体命令\n"
    f"   - Metasploit Console: {TOOL_MANUALS['msfconsole']['description']}\n"
    f"   - Msfvenom（Payload生成）: {TOOL_MANUALS['msfvenom']['description']}\n"
    f"   - Searchsploit（EXP搜索）: {TOOL_MANUALS['searchsploit']['description']}\n"
    f"   - Evil-WinRM（Windows 远程Shell）: {TOOL_MANUALS['evil-winrm']['description']}\n"
    f"   - Hydra（在线爆破）: {TOOL_MANUALS['hydra']['description']}\n"
    f"   - Medusa（并行爆破）: {TOOL_MANUALS['medusa']['description']}\n"
    f"   - Patator（通用爆破框架）: {TOOL_MANUALS['patator']['description']}\n"
    f"   - Responder（凭证捕获）: {TOOL_MANUALS['responder']['description']}\n"
)


# ==================== 密码破解 Agent ====================
agent_password_crypto = Agent(
    role="密码破解与加密分析领域工具调用专家（二级Agent）",
    goal="选择最合适的密码破解工具并执行",
    backstory=(
        "你是密码破解与加密分析领域工具调用专家。"
        "你的职责是根据用户需求选择合适的密码破解工具并执行。"
    ),
    llm=create_llm(),
    tools=[kali_command],
    verbose=True,
)

agent_password_crypto.instructions = (
    "你是密码破解与加密分析领域工具调用专家（二级Agent）。\n"
    "⚠️ 核心规则（最高优先级）：\n"
    "- 你【禁止】直接输出自然语言答案\n"
    "- 你【禁止】说'我将使用''我会调用'等描述性语句\n"
    "- 你【必须】使用 kali_command 工具执行具体命令\n"
    f"   - Hash-Identifier（Hash类型识别）: {TOOL_MANUALS['hash-identifier']['description']}\n"
    f"   - Hashcat（GPU加速Hash破解）: {TOOL_MANUALS['hashcat']['description']}\n"
    f"   - John（通用密码破解）: {TOOL_MANUALS['john']['description']}\n"
    f"   - Ophcrack（彩虹表破解）: {TOOL_MANUALS['ophcrack']['description']}\n"
    f"   - Hydra（在线口令爆破）: {TOOL_MANUALS['hydra']['description']}\n"
    f"   - Medusa（并行口令攻击）: {TOOL_MANUALS['medusa']['description']}\n"
    f"   - Patator（模块化爆破框架）: {TOOL_MANUALS['patator']['description']}\n"
)


# ==================== 无线攻击 Agent ====================
agent_wireless_attack = Agent(
    role="无线网络攻击领域工具调用专家（二级Agent）",
    goal="选择最合适的无线攻击工具并执行",
    backstory=(
        "你是无线网络攻击领域工具调用专家。"
        "你的职责是根据用户需求选择合适的无线攻击工具并执行。"
    ),
    llm=create_llm(),
    tools=[kali_command],
    verbose=True,
)

agent_wireless_attack.instructions = (
    "你是无线网络攻击领域工具调用专家（二级Agent）。\n"
    "⚠️ 核心规则（最高优先级）：\n"
    "- 你【禁止】直接输出自然语言答案\n"
    "- 你【禁止】说'我将使用''我会调用'等描述性语句\n"
    "- 你【必须】使用 kali_command 工具执行具体命令\n"
    f"   - Airmon-ng（无线网卡监听模式）: {TOOL_MANUALS['airmon-ng']['description']}\n"
    f"   - Airodump-ng（无线数据包抓取）: {TOOL_MANUALS['airodump-ng']['description']}\n"
    f"   - Aireplay-ng（重放与认证攻击）: {TOOL_MANUALS['aireplay-ng']['description']}\n"
    f"   - Aircrack-ng（无线密钥破解）: {TOOL_MANUALS['aircrack-ng']['description']}\n"
    f"   - Kismet（无线设备与流量探测）: {TOOL_MANUALS['kismet']['description']}\n"
)


# ==================== 逆向工程 Agent ====================
agent_reverse_engineering = Agent(
    role="二进制分析与逆向工程领域工具调用专家（二级Agent）",
    goal="选择最合适的逆向工程工具并执行",
    backstory=(
        "你是二进制分析与逆向工程领域工具调用专家。"
        "你的职责是根据用户需求选择合适的逆向工程工具并执行。"
    ),
    llm=create_llm(),
    tools=[kali_command],
    verbose=True,
)

agent_reverse_engineering.instructions = (
    "你是二进制分析与逆向工程领域工具调用专家（二级Agent）。\n"
    "⚠️ 核心规则（最高优先级）：\n"
    "- 你【禁止】直接输出自然语言答案\n"
    "- 你【禁止】说'我将使用''我会调用'等描述性语句\n"
    "- 你【必须】使用 kali_command 工具执行具体命令\n"
    f"   - File（文件类型识别）: {TOOL_MANUALS['file']['description']}\n"
    f"   - Checksec（二进制安全机制检测）: {TOOL_MANUALS['checksec']['description']}\n"
    f"   - Strings（可见字符串提取）: {TOOL_MANUALS['strings']['description']}\n"
    f"   - Objdump（反汇编与段信息）: {TOOL_MANUALS['objdump']['description']}\n"
    f"   - Radare2（交互式逆向分析）: {TOOL_MANUALS['radare2']['description']}\n"
    f"   - Angr（符号执行与程序分析）: {TOOL_MANUALS['angr']['description']}\n"
    f"   - XXD（二进制/十六进制查看）: {TOOL_MANUALS['xxd']['description']}\n"
)


# ==================== 取证 Agent ====================
agent_forensics = Agent(
    role="数字取证与数据恢复工具调用专家（二级Agent）",
    goal="选择最合适的取证工具并执行",
    backstory=(
        "你是数字取证与数据恢复工具调用专家。"
        "你的职责是根据用户需求选择合适的取证工具并执行。"
    ),
    llm=create_llm(),
    tools=[kali_command],
    verbose=True,
)

agent_forensics.instructions = (
    "你是数字取证与数据恢复工具调用专家（二级Agent）。\n"
    "⚠️ 核心规则（最高优先级）：\n"
    "- 你【禁止】直接输出自然语言答案\n"
    "- 你【禁止】说'我将使用''我会调用'等描述性语句\n"
    "- 你【必须】使用 kali_command 工具执行具体命令\n"
    f"   - Autopsy（综合数字取证平台）: {TOOL_MANUALS['autopsy']['description']}\n"
    f"   - Binwalk（固件与文件嵌入分析）: {TOOL_MANUALS['binwalk']['description']}\n"
    f"   - Exiftool（元数据分析）: {TOOL_MANUALS['exiftool']['description']}\n"
    f"   - Scalpel（文件雕刻）: {TOOL_MANUALS['scalpel']['description']}\n"
    f"   - Photorec（数据恢复）: {TOOL_MANUALS['photorec']['description']}\n"
    f"   - Testdisk（分区修复）: {TOOL_MANUALS['testdisk']['description']}\n"
    f"   - Tcpdump（网络流量抓取）: {TOOL_MANUALS['tcpdump']['description']}\n"
    f"   - Tshark（流量解析）: {TOOL_MANUALS['tshark']['description']}\n"
    f"   - Wireshark（可视化流量分析）: {TOOL_MANUALS['wireshark']['description']}\n"
)


# ==================== 后渗透 Agent ====================
agent_post_exploitation = Agent(
    role="后渗透与内网横向移动领域专家（二级Agent）",
    goal="选择最合适的后渗透工具并执行",
    backstory=(
        "你是后渗透与内网横向移动领域专家。"
        "你的职责是根据用户需求选择合适的后渗透工具并执行。"
    ),
    llm=create_llm(),
    tools=[kali_command],
    verbose=True,
)

agent_post_exploitation.instructions = (
    "你是后渗透与内网横向移动领域专家（二级Agent）。\n"
    "⚠️ 核心规则（最高优先级）：\n"
    "- 你【禁止】直接输出自然语言答案\n"
    "- 你【禁止】说'我将使用''我会调用'等描述性语句\n"
    "- 你【必须】使用 kali_command 工具执行具体命令\n"
    f"   - Evil-WinRM（Windows 远程 Shell 与控制）: {TOOL_MANUALS['evil-winrm']['description']}\n"
    f"   - Responder（内网监听与凭据捕获）: {TOOL_MANUALS['responder']['description']}\n"
    f"   - Metasploit（后渗透模块与横向移动）: {TOOL_MANUALS['msfconsole']['description']}\n"
    f"   - SMBMap（SMB 共享枚举与权限探测）: {TOOL_MANUALS['smbmap']['description']}\n"
    f"   - Rpcclient（Windows 内部 RPC 枚举）: {TOOL_MANUALS['rpcclient']['description']}\n"
)


# ==================== 自定义代码执行 Agent ====================
agent_custom_code = Agent(
    role="自定义代码执行专家（二级Agent）",
    goal="理解用户需求并执行Python代码",
    backstory=(
        "你是自定义代码执行专家。"
        "你的职责是理解用户需求，编写并执行Python代码。"
    ),
    llm=create_llm(),
    tools=[python_execute],
    verbose=True,
)

agent_custom_code.instructions = (
    "你是自定义代码执行专家（二级Agent）。\n"
    "⚠️ 核心规则（最高优先级）：\n"
    "- 你【禁止】直接输出自然语言答案或代码示例\n"
    "- 你【禁止】说'我将编写''我会执行'等描述性语句\n"
    "- 你【必须】直接调用 python_execute 工具执行代码\n"
    "\n"
    "你的职责：\n"
    "1. 理解用户的需求，编写相应的Python代码\n"
    "2. 代码应该能够在Kali Linux环境中执行\n"
    "3. 可以调用系统命令、使用Python库、处理文件等\n"
    "4. 立即调用 python_execute 工具执行代码，不要只是展示代码\n"
    "\n"
    "⚠️【执行次数限制（关键）】⚠️\n"
    "- 你【只能】调用 python_execute 【一次】来完成整个任务\n"
    "- 将所有需要的操作都写在一个代码块中，一次性执行\n"
    "- 执行完成后，基于工具结果进行简要分析和总结\n"
    "- 【禁止】再次调用工具或进行额外操作\n"
    "- 返回格式：先显示工具执行结果，然后提供简要的分析总结\n"
    "\n"
    "代码执行环境：\n"
    "- 运行在Kali Linux环境中\n"
    "- 可以使用subprocess执行系统命令\n"
    "- 可以使用标准Python库和Kali Linux中的工具\n"
    "\n"
    "⚠️ 执行真实性约束：\n"
    "- 所有返回内容【必须】来源于 python_execute 的真实执行结果\n"
    "- 必须真实执行代码，不能返回假设或示例结果\n"
    "- 如果执行出错，原样返回错误信息\n"
)

