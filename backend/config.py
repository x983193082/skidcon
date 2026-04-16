"""
SkidCon 配置模块
包含 OpenRouter API 配置、Kali 工具路径、超时设置等
"""

import os
from dotenv import load_dotenv
from pathlib import Path

# 加载环境变量
load_dotenv()

# OpenRouter API 配置
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "z-ai/glm-5.1")

# 任务配置
MAX_CONCURRENT_TASKS = int(os.getenv("MAX_CONCURRENT_TASKS", "3"))
TASK_TIMEOUT = int(os.getenv("TASK_TIMEOUT", "1800"))  # 30分钟

# 路径配置
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
TASKS_DIR = DATA_DIR / "tasks"
REPORTS_DIR = DATA_DIR / "reports"
WORDLISTS_DIR = BASE_DIR / "wordlists"

# 确保目录存在
TASKS_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Kali 工具路径配置
KALI_TOOLS = {
    # 扫描类
    "nmap": "/usr/bin/nmap",
    "masscan": "/usr/bin/masscan",
    "rustscan": "/usr/bin/rustscan",
    "naabu": "/usr/bin/naabu",
    
    # Web 类
    "sqlmap": "/usr/bin/sqlmap",
    "gobuster": "/usr/bin/gobuster",
    "dirb": "/usr/bin/dirb",
    "dirbuster": "/usr/bin/dirbuster",
    "ffuf": "/usr/bin/ffuf",
    "nikto": "/usr/bin/nikto",
    "wpscan": "/usr/bin/wpscan",
    "joomscan": "/usr/bin/joomscan",
    "droopescan": "/usr/bin/droopescan",
    
    # 漏洞利用
    "msfconsole": "/usr/bin/msfconsole",
    "searchsploit": "/usr/bin/searchsploit",
    "nuclei": "/usr/bin/nuclei",
    
    # 信息收集
    "whois": "/usr/bin/whois",
    "dig": "/usr/bin/dig",
    "nslookup": "/usr/bin/nslookup",
    "host": "/usr/bin/host",
    "theharvester": "/usr/bin/theHarvester",
    "amass": "/usr/bin/amass",
    "subfinder": "/usr/bin/subfinder",
    "assetfinder": "/usr/bin/assetfinder",
    "dnsrecon": "/usr/bin/dnsrecon",
    "dnsenum": "/usr/bin/dnsenum",
    
    # 服务枚举
    "enum4linux": "/usr/bin/enum4linux",
    "smbclient": "/usr/bin/smbclient",
    "snmpwalk": "/usr/bin/snmpwalk",
    "onesixtyone": "/usr/bin/onesixtyone",
    
    # 密码攻击
    "hydra": "/usr/bin/hydra",
    "john": "/usr/bin/john",
    "hashcat": "/usr/bin/hashcat",
    "crunch": "/usr/bin/crunch",
    "cewl": "/usr/bin/cewl",
    
    # 后渗透
    "pspy": "/opt/pspy/pspy64",
    "linpeas": "/opt/linpeas/linpeas.sh",
    "winpeas": "/opt/winpeas/winPEAS.bat",
    "linenum": "/opt/linenum/LinEnum.sh",
    "linux-exploit-suggester": "/opt/linux-exploit-suggester/linux-exploit-suggester.sh",
    
    # 其他
    "curl": "/usr/bin/curl",
    "wget": "/usr/bin/wget",
    "nc": "/usr/bin/nc",
    "socat": "/usr/bin/socat",
    "proxychains": "/usr/bin/proxychains",
    
    # 额外工具
    "whatweb": "/usr/bin/whatweb",
    "fierce": "/usr/bin/fierce",
    "dnsmap": "/usr/bin/dnsmap",
    "recon-ng": "/usr/bin/recon-ng",
    "maltego": "/usr/bin/maltego",
    "burpsuite": "/usr/bin/burpsuite",
    "zap": "/usr/bin/zap",
    "arachni": "/usr/bin/arachni",
    "skipfish": "/usr/bin/skipfish",
    "w3af": "/usr/bin/w3af",
    "commix": "/usr/bin/commix",
    "xsser": "/usr/bin/xsser",
    "beef": "/usr/bin/beef",
    "setoolkit": "/usr/bin/setoolkit",
    "aircrack-ng": "/usr/bin/aircrack-ng",
    "reaver": "/usr/bin/reaver",
    "bully": "/usr/bin/bully",
    "wifite": "/usr/bin/wifite",
    "ettercap": "/usr/bin/ettercap",
    "bettercap": "/usr/bin/bettercap",
    "responder": "/usr/bin/responder",
    "impacket": "/usr/bin/impacket",
    "bloodhound": "/usr/bin/bloodhound",
    "crackmapexec": "/usr/bin/crackmapexec",
    "evil-winrm": "/usr/bin/evil-winrm",
    "rdesktop": "/usr/bin/rdesktop",
    "xfreerdp": "/usr/bin/xfreerdp",
    "remmina": "/usr/bin/remmina",
    "wireshark": "/usr/bin/wireshark",
    "tcpdump": "/usr/bin/tcpdump",
    "tshark": "/usr/bin/tshark",
}

# 字典文件路径
DIRECTORIES_WORDLIST = WORDLISTS_DIR / "directories.txt"
SUBDOMAINS_WORDLIST = WORDLISTS_DIR / "subdomains.txt"

# 默认字典内容（如果文件不存在则创建）
DEFAULT_DIRECTORIES = """
admin
login
dashboard
api
v1
v2
config
backup
db
database
uploads
files
images
css
js
assets
static
media
tmp
temp
test
dev
staging
prod
""".strip()

DEFAULT_SUBDOMAINS = """
www
mail
ftp
smtp
pop
imap
dns
ns1
ns2
mx
webmail
admin
api
dev
staging
test
blog
shop
store
portal
app
mobile
m
cdn
static
assets
files
download
docs
wiki
help
support
""".strip()

def ensure_wordlists():
    """确保字典文件存在"""
    if not DIRECTORIES_WORDLIST.exists():
        with open(DIRECTORIES_WORDLIST, "w") as f:
            f.write(DEFAULT_DIRECTORIES)
    
    if not SUBDOMAINS_WORDLIST.exists():
        with open(SUBDOMAINS_WORDLIST, "w") as f:
            f.write(DEFAULT_SUBDOMAINS)

# 初始化字典文件
ensure_wordlists()
