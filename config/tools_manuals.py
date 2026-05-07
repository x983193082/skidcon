TOOL_MANUALS = {
    # =========================
    # 1️⃣ 信息收集（Recon / OSINT）
    # =========================
    "amass": {
        "description": "子域名枚举与攻击面发现工具",
        "manual": """
使用命令行方式调用 amass enum -d <domain>
通过 Python subprocess 执行并捕获 stdout
""",
        "return_format": {"type": "json", "schema": {"domains": ["string"]}},
    },
    "theharvester": {
        "description": "基于公开数据源收集邮箱、子域名、IP",
        "manual": """
使用 theHarvester -d <domain> -b all
解析文本输出中的 emails / hosts
""",
        "return_format": {
            "type": "json",
            "schema": {"emails": ["string"], "hosts": ["string"]},
        },
    },
    "recon-ng": {
        "description": "模块化 OSINT 框架",
        "manual": """
以非交互模式执行 recon-ng 脚本
提取模块运行结果
""",
        "return_format": {"type": "json", "schema": {"results": ["string"]}},
    },
    "spiderfoot": {
        "description": "自动化 OSINT 收集与关联分析工具",
        "manual": """
通过命令行运行 spiderfoot
解析生成的 JSON/CSV 结果
""",
        "return_format": {
            "type": "json",
            "schema": {"artifacts": [{"type": "string", "value": "string"}]},
        },
    },
    "fierce": {
        "description": "DNS 枚举工具",
        "manual": """
执行 fierce --domain <domain>
解析子域名与 IP
""",
        "return_format": {
            "type": "json",
            "schema": {"subdomains": [{"domain": "string", "ip": "string"}]},
        },
    },
    "dnsenum": {
        "description": "DNS 枚举与区域传送检测工具",
        "manual": """
执行 dnsenum <domain>
解析输出中的 DNS 记录
""",
        "return_format": {
            "type": "json",
            "schema": {"records": [{"type": "string", "value": "string"}]},
        },
    },
    "nbtscan": {
        "description": "NetBIOS 主机信息探测工具",
        "manual": """
执行 nbtscan <CIDR>
解析主机名与 IP
""",
        "return_format": {
            "type": "json",
            "schema": {"hosts": [{"ip": "string", "name": "string"}]},
        },
    },
    "arp-scan": {
        "description": "ARP 网络扫描工具",
        "manual": """
执行 arp-scan <interface> --localnet
解析 IP/MAC
""",
        "return_format": {
            "type": "json",
            "schema": {"devices": [{"ip": "string", "mac": "string"}]},
        },
    },
    "kismet": {
        "description": "无线监听与设备发现工具",
        "manual": """
通过命令行启动 kismet 日志模式
解析生成的设备信息
""",
        "return_format": {
            "type": "json",
            "schema": {"devices": [{"mac": "string", "type": "string"}]},
        },
    },
    "wafw00f": {
        "description": "Web 应用防火墙识别工具",
        "manual": """
执行 wafw00f <url>
解析识别结果
""",
        "return_format": {"type": "json", "schema": {"waf": "string"}},
    },
    # =========================
    # 2️⃣ 网络扫描与服务发现
    # =========================
    "nmap": {
        "description": "网络扫描工具，用于端口扫描、服务识别、操作系统检测",
        "manual": """
⚠️ 分阶段扫描策略（必须严格遵守）⚠️

════════════════════════════════════════════════
阶段1 - 快速端口发现（10-30秒）：
════════════════════════════════════════════════
  nmap -sS -T4 -Pn --top-ports 1000 <target>
  → 发现开放端口后立即进入阶段2

════════════════════════════════════════════════
阶段2 - 针对性版本探测（1-3分钟）：
════════════════════════════════════════════════
  仅对阶段1发现的开放端口执行：
  nmap -sV -T4 -Pn -p <发现的端口列表> <target>

════════════════════════════════════════════════
阶段3 - 选择性脚本扫描（仅按需）：
════════════════════════════════════════════════
  nmap -sC -T4 -Pn -p <特定端口> <target>
  → 仅对需要深入探测的特定端口使用

════════════════════════════════════════════════
🔥 扫描结果判断与下一步行动 🔥
════════════════════════════════════════════════
✅ 有开放端口 → 对开放端口执行阶段2版本探测
✅ 部分开放部分filtered → 对开放端口执行阶段2，考虑防火墙绕过
🔴 所有端口 filtered → 【停止扫描！】目标有防火墙，换用以下策略：
   - Web渗透：尝试 httpx/curl 访问常见Web端口
   - 目录爆破：使用 gobuster/ffuf 扫描Web路径
   - 凭据爆破：使用 hydra 尝试常见默认凭据
   - 漏洞扫描：使用 nikto/wpscan 扫描Web服务
   - 不要继续执行更多nmap扫描！
🔴 所有端口 closed → 目标不在线或完全封锁，检查目标IP是否正确

════════════════════════════════════════════════
常用命令模板：
════════════════════════════════════════════════
  nmap -sS -T4 -Pn --top-ports 1000 <target>
  nmap -sS -T4 -Pn -p 22,80,443,3306,5432,6379,8080,8443,8888 <target>
  nmap -sV -T4 -Pn -p <发现的端口> <target>
  nmap -O -T4 -Pn <target>

════════════════════════════════════════════════
绝对禁止：
════════════════════════════════════════════════
❌ nmap -sV -sC -p- <target>          # 数小时
❌ nmap -sV -sC -T4 -p- <target>      # 数小时
❌ nmap -p- <target>                   # 全端口作为第一步
❌ nmap -Pn -sS -T1 -p 1-65535         # 极慢，无意义
❌ 端口全filtered时继续执行nmap扫描     # 浪费时间
""",
        "return_format": {
            "type": "json",
            "schema": {
                "hosts": [
                    {
                        "ip": "string",
                        "ports": [
                            {
                                "port": "int",
                                "protocol": "string",
                                "state": "string",
                                "service": "string",
                            }
                        ],
                    }
                ]
            },
        },
    },
    "masscan": {
        "description": "高速端口扫描工具，用于大范围快速发现开放端口",
        "manual": """
⚠️ masscan 使用规则 ⚠️

使用场景：
- 仅用于大网段（/16以上）快速端口发现
- 单个IP请直接用nmap，不要用masscan
- 发现开放端口后交给 nmap -sV 做详细枚举

════════════════════════════════════════════════
推荐命令：
════════════════════════════════════════════════
快速扫描子网所有端口：
  masscan <subnet>/24 -p1-65535 --rate=10000
扫描子网常见Web端口：
  masscan <subnet>/24 -p80,443,8080,8443 --rate=5000
输出到文件：
  masscan <target> -p1-65535 --rate=10000 -oL results.txt

════════════════════════════════════════════════
配合nmap工作流：
════════════════════════════════════════════════
  1. masscan 快速发现开放端口
  2. nmap -sV -p <发现的端口> 做详细枚举

════════════════════════════════════════════════
绝对禁止：
════════════════════════════════════════════════
❌ masscan对单个IP使用（直接用nmap更快更准）
❌ --rate超过10000（可能导致网络拥塞或被封）
❌ masscan后不做nmap详细枚举（masscan只发现端口不识别服务）
""",
        "return_format": {
            "type": "json",
            "schema": {"open_ports": [{"ip": "string", "port": "int"}]},
        },
    },
    "tcpdump": {
        "description": "网络流量抓包工具",
        "manual": """
执行 tcpdump -i <iface> -c <count>
解析抓取的包摘要
""",
        "return_format": {
            "type": "json",
            "schema": {
                "packets": [{"src": "string", "dst": "string", "protocol": "string"}]
            },
        },
    },
    "tshark": {
        "description": "命令行版 Wireshark",
        "manual": """
使用 tshark 读取 pcap 或实时抓包
""",
        "return_format": {"type": "json", "schema": {"frames": ["string"]}},
    },
    "wireshark": {
        "description": "图形化网络分析工具（仅解析输出）",
        "manual": """
读取已有 pcap 文件，不启动 GUI
""",
        "return_format": {"type": "json", "schema": {"summary": "string"}},
    },
    "httpx": {
        "description": "HTTP 服务探测与指纹识别工具",
        "manual": """
执行 httpx -u <url>
解析状态码、标题、指纹,页面内容
""",
        "return_format": {
            "type": "json",
            "schema": {
                "http_services": [
                    {
                        "url": "string",
                        "status": "int",
                        "title": "string",
                        "fingerprint": "string",
                        "body": "string",
                    }
                ]
            },
        },
    },
    "curl": {
        "description": "HTTP 请求工具",
        "manual": """
通过 curl 发起 HTTP 请求
捕获响应，注意添加-L允许重定向
""",
        "return_format": {
            "type": "json",
            "schema": {"status": "int", "headers": "string", "body": "string"},
        },
    },
    # =========================
    # 3️⃣ 枚举 / 4️⃣ Web / 5️⃣ Exploit / 6️⃣ Crypto / 7️⃣ Wireless / 8️⃣ Reverse / 9️⃣ Forensics / 🔟 Post
    # =========================
    "enum4linux": {
        "description": "Windows / Samba 枚举工具",
        "manual": """
执行 enum4linux <ip>
解析用户、共享、SID 等信息
""",
        "return_format": {
            "type": "json",
            "schema": {"users": ["string"], "shares": ["string"]},
        },
    },
    "rpcclient": {
        "description": "RPC 服务枚举工具",
        "manual": """
使用 rpcclient -U '' <ip> 执行枚举命令
解析返回内容
""",
        "return_format": {"type": "json", "schema": {"rpc_info": ["string"]}},
    },
    "smbmap": {
        "description": "SMB 共享与权限枚举工具",
        "manual": """
执行 smbmap -H <ip>
解析共享权限
""",
        "return_format": {
            "type": "json",
            "schema": {"shares": [{"name": "string", "permission": "string"}]},
        },
    },
    "dirb": {
        "description": "Web 目录爆破工具",
        "manual": """
执行 dirb <url> -S
常用字典：/usr/share/wordlists/dirb/common.txt
带认证：dirb <url> -S -u <user>:<password>
""",
        "return_format": {"type": "json", "schema": {"paths": ["string"]}},
    },
    "gobuster": {
        "description": "高性能目录与子域枚举工具",
        "manual": """
⚠️ gobuster 使用规则 ⚠️

════════════════════════════════════════════════
目录枚举（最常用）：
════════════════════════════════════════════════
基础扫描：
  gobuster dir -u <url> -w /usr/share/wordlists/dirb/common.txt

带认证的扫描：
  gobuster dir -u <url> -w /usr/share/wordlists/dirb/common.txt -U <user> -P <password>

排除特定状态码（如排除401）：
  gobuster dir -u <url> -w /usr/share/wordlists/dirb/common.txt -b 401

指定状态码白名单：
  gobuster dir -u <url> -w /usr/share/wordlists/dirb/common.txt -s "200,204,301,302,307,403"

════════════════════════════════════════════════
子域名枚举：
════════════════════════════════════════════════
  gobuster dns -d <domain> -w /usr/share/seclists/Discovery/DNS/subdomains-top1million-5000.txt

════════════════════════════════════════════════
推荐字典（按大小）：
════════════════════════════════════════════════
  /usr/share/wordlists/dirb/common.txt              - 小（~4600条，快）
  /usr/share/seclists/Discovery/Web-Content/common.txt - 中（~4700条）
  /usr/share/wordlists/dirbuster/directory-list-2.3-medium.txt - 大（仅最后手段）

════════════════════════════════════════════════
绝对禁止：
════════════════════════════════════════════════
❌ 同时使用 -s 和 -b 参数（会报错，只能用其中一个）
❌ 对需要认证的站点不提供 -U/-P 参数（所有路径都返回401无意义）
❌ 第一次扫描就用大字典（先用 common.txt 快速发现，再用大字典补充）
""",
        "return_format": {
            "type": "json",
            "schema": {"paths": ["string"]},
        },
    },
    "ffuf": {
        "description": "快速模糊测试/路径枚举工具",
        "manual": """
目录枚举：
  ffuf -u <url>/FUZZ -w /usr/share/wordlists/dirb/common.txt -mc 200,204,301,302,307,403
带认证：
  ffuf -u <url>/FUZZ -w /usr/share/wordlists/dirb/common.txt -H "Authorization: Basic <base64>"
排除401：
  ffuf -u <url>/FUZZ -w /usr/share/wordlists/dirb/common.txt -fc 401
""",
        "return_format": {
            "type": "json",
            "schema": {"matches": [{"url": "string", "status": "int"}]},
        },
    },
    "wfuzz": {
        "description": "Web 参数与目录模糊测试工具",
        "manual": """
执行 wfuzz -c -z file,<wordlist> <url>
""",
        "return_format": {"type": "json", "schema": {"results": ["string"]}},
    },
    "nikto": {
        "description": "Web 漏洞扫描与配置检测工具",
        "manual": """
执行 nikto -h <url>
""",
        "return_format": {"type": "json", "schema": {"issues": ["string"]}},
    },
    "wpscan": {
        "description": "WordPress 枚举与漏洞扫描工具",
        "manual": """
执行 wpscan --url <url>
""",
        "return_format": {"type": "json", "schema": {"findings": ["string"]}},
    },
    "nxc": {
        "description": "多协议枚举与横向渗透工具（NetExec）",
        "manual": """
执行 nxc smb <ip>
解析枚举输出
""",
        "return_format": {"type": "json", "schema": {"results": ["string"]}},
    },
    "burpsuite": {
        "description": "Web 请求拦截与重放工具（导出请求分析）",
        "manual": """
解析 Burp 导出的 HTTP 请求/响应数据
""",
        "return_format": {
            "type": "json",
            "schema": {"requests": ["string"], "responses": ["string"]},
        },
    },
    "sqlmap": {
        "description": "自动化 SQL 注入利用工具",
        "manual": """
执行 sqlmap -u <url> --batch
""",
        "return_format": {
            "type": "json",
            "schema": {"databases": ["string"], "tables": ["string"]},
        },
    },
    "msfconsole": {
        "description": "Metasploit 框架，用于漏洞利用与后渗透操作",
        "manual": """
通过 msfconsole 非交互脚本模式
执行 exploit 模块、后渗透模块、内网扫描、凭据收集等操作
解析 session 与模块输出
""",
        "return_format": {
            "type": "json",
            "schema": {
                "sessions": [
                    {"session_id": "string", "type": "string", "target": "string"}
                ]
            },
        },
    },
    "msfvenom": {
        "description": "Payload 生成工具",
        "manual": """
执行 msfvenom 生成 Payload 文件
""",
        "return_format": {"type": "json", "schema": {"payload_path": "string"}},
    },
    "searchsploit": {
        "description": "本地 Exploit 数据库搜索工具",
        "manual": """
执行 searchsploit <keyword>
""",
        "return_format": {
            "type": "json",
            "schema": {"exploits": [{"id": "string", "title": "string"}]},
        },
    },
    "evil-winrm": {
        "description": "基于 WinRM 的 Windows 后渗透交互式 Shell 工具",
        "manual": """
通过 evil-winrm 连接已获取凭据的 Windows 主机
执行系统命令、上传下载文件、权限验证
使用 Python subprocess 调用命令行并捕获输出
""",
        "return_format": {
            "type": "json",
            "schema": {"host": "string", "user": "string", "output": ["string"]},
        },
    },
    "hydra": {
        "description": "多协议口令爆破工具",
        "manual": """
⚠️ hydra 使用规则（必须严格遵守）⚠️

════════════════════════════════════════════════
分阶段爆破策略：
════════════════════════════════════════════════
阶段1 - 快速弱口令尝试（几秒~1分钟）：
  hydra -l admin -P /usr/share/wordlists/fasttrack.txt -s <port> <target> <service>
  → 必须先用小字典！绝大多数弱口令都能在这里找到

阶段2 - 中等字典（1~3分钟）：
  hydra -l admin -P /usr/share/wordlists/best1050.txt -s <port> <target> <service>
  → 仅在阶段1失败时使用

════════════════════════════════════════════════
常用命令模板（直接使用）：
════════════════════════════════════════════════
HTTP基础认证爆破：
  hydra -l admin -P /usr/share/wordlists/fasttrack.txt <target> http-get / -s <port>
SSH爆破：
  hydra -l root -P /usr/share/wordlists/fasttrack.txt <target> ssh
FTP爆破：
  hydra -l admin -P /usr/share/wordlists/fasttrack.txt <target> ftp
多用户名尝试：
  hydra -L /usr/share/wordlists/fasttrack.txt -P /usr/share/wordlists/fasttrack.txt <target> <service> -s <port>

════════════════════════════════════════════════
绝对禁止：
════════════════════════════════════════════════
❌ 禁止使用 rockyou.txt（1400万条，HTTP认证需数天才能跑完）
❌ 禁止不指定并发数限制（必须加 -t 4 或 -t 10）
❌ 禁止长时间爆破（超过5分钟应中断换策略）

════════════════════════════════════════════════
推荐字典：
════════════════════════════════════════════════
  fasttrack.txt    - 极小（几百条，几秒完成）← 始终先用这个
  best1050.txt     - 小（1050条，1~3分钟）← fasttrack失败后用
  ⛔ rockyou.txt   - 禁止使用（1400万条，会卡死）
""",
        "return_format": {
            "type": "json",
            "schema": {"credentials": [{"user": "string", "password": "string"}]},
        },
    },
    "medusa": {
        "description": "并行密码爆破工具",
        "manual": """
执行 medusa -h <host> -u <user> -P <passlist>
""",
        "return_format": {
            "type": "json",
            "schema": {"credentials": [{"user": "string", "password": "string"}]},
        },
    },
    "patator": {
        "description": "模块化暴力破解框架",
        "manual": """
执行 patator 模块化攻击
""",
        "return_format": {"type": "json", "schema": {"results": ["string"]}},
    },
    "responder": {
        "description": "LLMNR/NBT-NS 欺骗与凭据捕获工具",
        "manual": """
在内网环境中运行 responder
捕获 NTLMv1/v2 Hash 信息
解析并结构化输出
""",
        "return_format": {
            "type": "json",
            "schema": {
                "captured_hashes": [
                    {"username": "string", "hash": "string", "protocol": "string"}
                ]
            },
        },
    },
    "hashcat": {
        "description": "GPU 加速 Hash 破解工具",
        "manual": """
执行 hashcat -m <mode> -a 0 <hash> <wordlist>
""",
        "return_format": {
            "type": "json",
            "schema": {"cracked": [{"hash": "string", "password": "string"}]},
        },
    },
    "john": {
        "description": "John the Ripper 密码破解工具",
        "manual": """
执行 john <hashfile>
""",
        "return_format": {
            "type": "json",
            "schema": {"cracked": [{"hash": "string", "password": "string"}]},
        },
    },
    "ophcrack": {
        "description": "基于彩虹表的密码破解工具",
        "manual": """
执行 ophcrack 并解析结果
""",
        "return_format": {"type": "json", "schema": {"passwords": ["string"]}},
    },
    "hash-identifier": {
        "description": "Hash 类型识别工具",
        "manual": """
执行 hash-identifier 并解析候选算法
""",
        "return_format": {"type": "json", "schema": {"possible_types": ["string"]}},
    },
    "airmon-ng": {
        "description": "无线网卡监听模式工具",
        "manual": """
执行 airmon-ng start <iface>
""",
        "return_format": {"type": "json", "schema": {"monitor_interface": "string"}},
    },
    "airodump-ng": {
        "description": "无线网络监听与抓包工具",
        "manual": """
执行 airodump-ng <iface>
""",
        "return_format": {
            "type": "json",
            "schema": {"networks": [{"bssid": "string", "channel": "int"}]},
        },
    },
    "aireplay-ng": {
        "description": "无线重放与去认证攻击工具",
        "manual": """
执行 aireplay-ng 攻击模式
""",
        "return_format": {"type": "json", "schema": {"status": "string"}},
    },
    "aircrack-ng": {
        "description": "无线密钥破解工具",
        "manual": """
执行 aircrack-ng <capture>
""",
        "return_format": {"type": "json", "schema": {"key": "string"}},
    },
    "angr": {
        "description": "基于符号执行的二进制分析工具",
        "manual": """
使用 Python angr API 进行分析
""",
        "return_format": {"type": "json", "schema": {"paths": ["string"]}},
    },
    "radare2": {
        "description": "交互式逆向工程框架",
        "manual": """
执行 r2 -c 指令并解析输出
""",
        "return_format": {"type": "json", "schema": {"functions": ["string"]}},
    },
    "objdump": {
        "description": "二进制反汇编工具",
        "manual": """
执行 objdump -d <binary>
""",
        "return_format": {"type": "json", "schema": {"assembly": ["string"]}},
    },
    "checksec": {
        "description": "二进制安全机制检测工具",
        "manual": """
执行 checksec <binary>
""",
        "return_format": {"type": "json", "schema": {"protections": ["string"]}},
    },
    "strings": {
        "description": "二进制字符串提取工具",
        "manual": """
执行 strings <binary>
""",
        "return_format": {"type": "json", "schema": {"strings": ["string"]}},
    },
    "file": {
        "description": "文件类型识别工具",
        "manual": """
执行 file <target>
""",
        "return_format": {"type": "json", "schema": {"file_type": "string"}},
    },
    "xxd": {
        "description": "十六进制查看与转换工具",
        "manual": """
执行 xxd <file>
""",
        "return_format": {"type": "json", "schema": {"hex": "string"}},
    },
    "autopsy": {
        "description": "数字取证分析平台",
        "manual": """
解析 Autopsy 项目导出结果
""",
        "return_format": {"type": "json", "schema": {"artifacts": ["string"]}},
    },
    "binwalk": {
        "description": "固件与嵌入文件分析工具",
        "manual": """
执行 binwalk <file>
""",
        "return_format": {"type": "json", "schema": {"embedded": ["string"]}},
    },
    "exiftool": {
        "description": "文件元数据分析工具",
        "manual": """
执行 exiftool <file>
""",
        "return_format": {"type": "json", "schema": {"metadata": {"key": "value"}}},
    },
    "photorec": {
        "description": "文件恢复工具",
        "manual": """
执行 photorec 并解析恢复列表
""",
        "return_format": {"type": "json", "schema": {"recovered_files": ["string"]}},
    },
    "testdisk": {
        "description": "磁盘分区与文件恢复工具",
        "manual": """
执行 testdisk 非交互恢复
""",
        "return_format": {"type": "json", "schema": {"partitions": ["string"]}},
    },
    "scalpel": {
        "description": "文件雕刻工具",
        "manual": """
执行 scalpel <image>
""",
        "return_format": {"type": "json", "schema": {"files": ["string"]}},
    },
    # =========================
    # 🔐 逻辑漏洞测试工具
    # =========================
    "idor_enum": {
        "description": "IDOR越权访问枚举与测试工具，用于测试直接对象引用漏洞",
        "manual": """
测试IDOR越权访问漏洞：
1. 识别可能存在IDOR的参数（user_id, order_id, file_id等）
2. 修改参数值尝试访问其他用户数据
3. 对比响应判断是否存在越权

测试命令示例：
curl -H "Cookie: session=xxx" "http://target/api/user/2/profile"
curl -H "Authorization: Bearer xxx" "http://target/api/orders/1001"

Python批量测试示例：
import requests
for i in range(1, 100):
    r = requests.get(f"http://target/api/user/{i}", cookies=cookies)
    if r.status_code == 200 and "data" in r.json():
        print(f"ID {i}: {r.json()}")
""",
        "return_format": {
            "type": "json",
            "schema": {
                "idor_findings": [
                    {
                        "endpoint": "string",
                        "param": "string",
                        "vulnerable": "bool",
                        "evidence": "string",
                    }
                ]
            },
        },
    },
    "race_condition": {
        "description": "并发竞争条件测试工具，用于测试并发操作漏洞（如重复使用优惠券、并发转账）",
        "manual": """
测试并发竞争条件漏洞：
1. 识别可能存在竞争条件的操作（支付、转账、优惠券使用等）
2. 同时发送多个相同请求
3. 检查是否产生预期外的结果

Python多线程测试示例：
import threading, requests, time

def send_request():
    r = requests.post(url, data=data, cookies=cookies)
    print(r.status_code, r.text)

threads = []
for _ in range(10):
    t = threading.Thread(target=send_request)
    threads.append(t)

for t in threads: t.start()
for t in threads: t.join()

# 检查是否产生了多次效果（如余额多次扣减、优惠券多次使用）
""",
        "return_format": {
            "type": "json",
            "schema": {
                "race_findings": [
                    {
                        "endpoint": "string",
                        "requests_sent": "int",
                        "unexpected_results": "int",
                        "vulnerable": "bool",
                    }
                ]
            },
        },
    },
    "param_tamper": {
        "description": "参数篡改测试工具，用于测试价格、数量、状态等参数是否可被篡改",
        "manual": """
测试参数篡改漏洞：
1. 捕获正常请求，识别可篡改参数（price, quantity, status, role等）
2. 修改参数值发送请求
3. 检查服务器是否正确验证参数

常见测试点：
- 价格篡改：price=0, price=-1, price=0.01
- 数量篡改：quantity=-1, quantity=999999
- 状态篡改：status=paid, status=completed, status=shipped
- 角色篡改：role=admin, is_admin=true, user_type=vip
- ID篡改：user_id=1, order_id=999

curl测试示例：
curl -X POST "http://target/api/order" -H "Content-Type: application/json" -d '{"price": 0, "quantity": 1}'
curl -X PUT "http://target/api/user" -d "role=admin"
""",
        "return_format": {
            "type": "json",
            "schema": {
                "tamper_findings": [
                    {
                        "param": "string",
                        "original_value": "string",
                        "tampered_value": "string",
                        "vulnerable": "bool",
                        "impact": "string",
                    }
                ]
            },
        },
    },
    "auth_bypass": {
        "description": "认证绕过测试工具，用于测试登录验证、权限检查是否可被绕过",
        "manual": """
认证绕过测试方法：

1. Cookie/Session伪造：
   - 修改Cookie中的用户标识（user_id, uid, id）
   - 修改Session中的权限标识（is_admin=true）

2. JWT Token篡改：
   - 修改payload中的用户信息
   - 尝试alg=none攻击
   - 尝试弱密钥签名

3. 路径绕过：
   - /admin -> /Admin, /admin/, /admin/., //admin
   - /api/user -> /api/User, /API/user

4. HTTP方法绕过：
   - GET改POST
   - 添加X-HTTP-Method-Override: PUT

5. 请求头绕过：
   - X-Forwarded-For: 127.0.0.1
   - X-Original-URL: /admin
   - X-Rewrite-URL: /admin
   - X-Real-IP: 127.0.0.1

curl测试示例：
curl -H "Cookie: admin=true" http://target/admin
curl -H "X-Original-URL: /admin" http://target/
curl -X POST -H "X-HTTP-Method-Override: PUT" http://target/api/user/1
""",
        "return_format": {
            "type": "json",
            "schema": {
                "bypass_findings": [
                    {
                        "method": "string",
                        "endpoint": "string",
                        "payload": "string",
                        "vulnerable": "bool",
                        "access_granted": "bool",
                    }
                ]
            },
        },
    },
    "business_bypass": {
        "description": "业务流程绕过测试工具，用于测试是否可跳过验证步骤",
        "manual": """
业务流程绕过测试：

1. 分析正常业务流程：
   - 支付流程：下单 -> 支付 -> 确认 -> 发货
   - 注册流程：填写信息 -> 邮箱验证 -> 激活 -> 登录

2. 尝试跳过中间步骤：
   - 跳过支付直接确认订单
   - 跳过邮箱验证直接登录
   - 跳过验证码直接提交

3. 尝试重复执行：
   - 重复使用一次性Token
   - 重复提交表单
   - 重复领取奖励

测试示例：
# 跳过支付直接确认
curl -X POST "http://target/api/order/confirm" -H "Cookie: session=xxx"

# 重复使用优惠券
for i in range(10):
    curl -X POST "http://target/api/coupon/use" -d "code=SAVE100"

# 跳过验证步骤
curl -X POST "http://target/api/register/complete" -d "email=victim@test.com"
""",
        "return_format": {
            "type": "json",
            "schema": {
                "bypass_findings": [
                    {
                        "step_skipped": "string",
                        "endpoint_accessed": "string",
                        "vulnerable": "bool",
                        "impact": "string",
                    }
                ]
            },
        },
    },
    # =========================
    # 🌐 4.浏览器自动化工具 (Playwright CLI)
    # =========================
    "browser_open": {
        "description": "打开浏览器并导航到指定URL，启动浏览器会话",
        "manual": """
命令: playwright-cli open <url> [options]

参数:
  <url>                              要打开的URL
  --browser=<type>                  浏览器类型: chromium/firefox/webkit/msedge (默认: chromium)
  --headed                           显示浏览器界面（默认无头模式）
  --persistent                       保存浏览器配置到磁盘（保持登录态）

示例:
  playwright-cli open https://example.com
  playwright-cli open https://example.com --browser=firefox
  playwright-cli open https://example.com --headed
  playwright-cli -s=stealth open https://example.com --persistent

⚠️ 重要:
  - open命令会启动一个持久浏览器会话
  - 后续命令（click、type、screenshot等）在同一会话中执行
  - 使用 playwright-cli close 关闭会话
  - 使用 -s=name 指定命名会话，支持多项目并行
""",
        "return_format": {
            "type": "text",
            "schema": {
                "page_url": "string",
                "page_title": "string",
                "snapshot": "string",
            },
        },
    },
    "browser_goto": {
        "description": "在当前浏览器会话中导航到新URL（不需要重新打开浏览器）",
        "manual": """
命令: playwright-cli goto <url>

示例:
  playwright-cli goto https://example.com/login
""",
        "return_format": {"type": "text"},
    },
    "browser_click": {
        "description": "点击页面元素，支持元素引用(ref)和CSS选择器",
        "manual": """
命令: playwright-cli click <ref_or_selector> [button]

参数:
  <ref_or_selector>    元素引用(如e15)或CSS选择器(如#submit-btn)
  [button]             可选: left/right/middle (默认: left)

先用 playwright-cli snapshot 获取元素ref

示例:
  playwright-cli click e15
  playwright-cli click "#submit-btn"
  playwright-cli click "role=button[name=Submit]"
  playwright-cli click "#menu" right
""",
        "return_format": {"type": "text"},
    },
    "browser_type": {
        "description": "在当前聚焦元素中输入文本（逐字符输入，模拟真实键盘）",
        "manual": """
命令: playwright-cli type <text>

示例:
  playwright-cli type "admin"
  playwright-cli type "hello world"
""",
        "return_format": {"type": "text"},
    },
    "browser_fill": {
        "description": "清空指定元素并填入文本（比type更快）",
        "manual": """
命令: playwright-cli fill <ref> <text>

示例:
  playwright-cli fill e5 "admin"
  playwright-cli fill "#username" "admin"
  playwright-cli fill "role=searchbox" "test"
""",
        "return_format": {"type": "text"},
    },
    "browser_screenshot": {
        "description": "截取当前页面或指定元素的截图",
        "manual": """
命令: playwright-cli screenshot [ref] [options]

参数:
  [ref]                     可选，截取指定元素
  --filename=<path>         保存到指定文件路径

示例:
  playwright-cli screenshot
  playwright-cli screenshot e15
  playwright-cli screenshot --filename=reports/screenshots/test.png
  playwright-cli pdf                    # 保存为PDF
""",
        "return_format": {"type": "text", "schema": {"screenshot_path": "string"}},
    },
    "browser_snapshot": {
        "description": "获取当前页面的可访问性快照，包含元素引用(ref)，用于定位交互元素",
        "manual": """
命令: playwright-cli snapshot [options]

参数:
  --filename=<path>         保存快照到指定文件

示例:
  playwright-cli snapshot
  playwright-cli snapshot --filename=page-snapshot.yml

⚠️ 重要:
  - 快照返回元素引用(如e15)，后续click/fill等操作使用这些引用
  - 页面DOM变化后，元素引用可能失效，需要重新snapshot
  - 在重大操作后应重新获取快照
""",
        "return_format": {"type": "text"},
    },
    "browser_eval": {
        "description": "在当前页面执行JavaScript代码并返回结果",
        "manual": """
命令: playwright-cli eval <function> [ref]

示例:
  playwright-cli eval "document.title"
  playwright-cli eval "document.cookie"
  playwright-cli eval "Array.from(document.links).map(l=>l.href)"
  playwright-cli eval "() => document.querySelector('#result').textContent"
  playwright-cli eval "el => el.getAttribute('href')" e8
""",
        "return_format": {"type": "text"},
    },
    "browser_press": {
        "description": "按下键盘按键（如Enter、Tab、Escape等）",
        "manual": """
命令: playwright-cli press <key>

常用按键: Enter, Tab, Escape, ArrowDown, ArrowUp, Backspace, Delete, Control+a

示例:
  playwright-cli press Enter
  playwright-cli press Tab
  playwright-cli press Escape
""",
        "return_format": {"type": "text"},
    },
    "browser_cookie_list": {
        "description": "列出当前页面的所有Cookie",
        "manual": """
命令: playwright-cli cookie-list [--domain=<domain>]

示例:
  playwright-cli cookie-list
  playwright-cli cookie-list --domain=example.com
""",
        "return_format": {"type": "text"},
    },
    "browser_cookie_set": {
        "description": "设置Cookie，用于模拟登录态或绕过认证",
        "manual": """
命令: playwright-cli cookie-set <name> <value>

示例:
  playwright-cli cookie-set session abc123
  playwright-cli cookie-set token "bearer eyJhbGci..."
""",
        "return_format": {"type": "text"},
    },
    "browser_cookie_delete": {
        "description": "删除指定名称的Cookie或清除所有Cookie",
        "manual": """
命令: playwright-cli cookie-delete <name>    # 删除指定Cookie
命令: playwright-cli cookie-clear             # 清除所有Cookie

示例:
  playwright-cli cookie-delete session
  playwright-cli cookie-clear
""",
        "return_format": {"type": "text"},
    },
    "browser_state_save": {
        "description": "保存当前浏览器状态（Cookie、localStorage等），用于后续恢复会话",
        "manual": """
命令: playwright-cli state-save [filename]

示例:
  playwright-cli state-save login_state.json
  playwright-cli state-save                    # 自动生成文件名
""",
        "return_format": {"type": "text"},
    },
    "browser_state_load": {
        "description": "加载之前保存的浏览器状态，恢复登录态",
        "manual": """
命令: playwright-cli state-load <filename>

示例:
  playwright-cli state-load login_state.json
""",
        "return_format": {"type": "text"},
    },
    "browser_network": {
        "description": "列出页面加载以来的所有网络请求，用于分析API调用",
        "manual": """
命令: playwright-cli network

示例:
  playwright-cli network
""",
        "return_format": {"type": "text"},
    },
    "browser_route": {
        "description": "模拟或拦截网络请求（Mock API）",
        "manual": """
命令:
  playwright-cli route <pattern> [opts]      # 拦截请求
  playwright-cli route-list                   # 列出活跃路由
  playwright-cli unroute <pattern>            # 移除路由

示例:
  playwright-cli route "**/api/**" --mock='{"status":200}'
  playwright-cli route-list
  playwright-cli unroute "**/api/**"
""",
        "return_format": {"type": "text"},
    },
    "browser_go_back": {
        "description": "浏览器后退",
        "manual": "命令: playwright-cli go-back",
        "return_format": {"type": "text"},
    },
    "browser_go_forward": {
        "description": "浏览器前进",
        "manual": "命令: playwright-cli go-forward",
        "return_format": {"type": "text"},
    },
    "browser_reload": {
        "description": "刷新当前页面",
        "manual": "命令: playwright-cli reload",
        "return_format": {"type": "text"},
    },
    "browser_close": {
        "description": "关闭当前浏览器会话",
        "manual": """命令: playwright-cli close

其他会话管理命令:
  playwright-cli list                           # 列出所有会话
  playwright-cli close-all                      # 关闭所有会话
  playwright-cli kill-all                       # 强制关闭所有浏览器进程""",
        "return_format": {"type": "text"},
    },
    "browser_tab_list": {
        "description": "标签页管理：列出、新建、切换、关闭标签页",
        "manual": """
命令: playwright-cli tab-list                   # 列出所有标签页
命令: playwright-cli tab-new [url]               # 新建标签页
命令: playwright-cli tab-select <index>           # 切换标签页
命令: playwright-cli tab-close [index]            # 关闭标签页

示例:
  playwright-cli tab-new https://example.com
  playwright-cli tab-select 1
  playwright-cli tab-close 1
""",
        "return_format": {"type": "text"},
    },
    "browser_console": {
        "description": "查看浏览器控制台消息，用于调试和提取日志",
        "manual": """
命令: playwright-cli console [min-level]

参数:
  min-level             最低日志级别: error/warning/info/log/verbose

示例:
  playwright-cli console
  playwright-cli console error
""",
        "return_format": {"type": "text"},
    },
    "browser_select": {
        "description": "在下拉框中选择选项",
        "manual": """
命令: playwright-cli select <ref> <value>

示例:
  playwright-cli select e13 "China"
""",
        "return_format": {"type": "text"},
    },
    "browser_hover": {
        "description": "鼠标悬停在指定元素上",
        "manual": """
命令: playwright-cli hover <ref>

示例:
  playwright-cli hover e15
""",
        "return_format": {"type": "text"},
    },
    "browser_upload": {
        "description": "上传文件",
        "manual": """
命令: playwright-cli upload <file_path>

示例:
  playwright-cli upload /tmp/test_file.txt
""",
        "return_format": {"type": "text"},
    },
    "browser_video_start": {
        "description": "开始录制浏览器操作视频",
        "manual": """命令: playwright-cli video-start

停止录制: playwright-cli video-stop --filename=reports/screenshots/demo.mp4
添加章节标记: playwright-cli video-chapter "登录完成"
""",
        "return_format": {"type": "text"},
    },
    "browser_run_code": {
        "description": "运行Playwright代码片段（高级操作，如等待、拖拽等）",
        "manual": """
命令: playwright-cli run-code <code>

示例:
  playwright-cli run-code "await page.waitForSelector('.dynamic-content')"
  playwright-cli run-code "await page.waitForTimeout(3000)"
  playwright-cli run-code "await page.waitForLoadState('networkidle')"
""",
        "return_format": {"type": "text"},
    },
    "browser_session": {
        "description": "浏览器会话管理，支持命名会话和多实例并行",
        "manual": """
命令:
  playwright-cli -s=<name> open <url>            # 使用命名会话
  playwright-cli list                             # 列出所有会话
  playwright-cli close-all                        # 关闭所有会话
  playwright-cli kill-all                         # 强制关闭所有浏览器进程
  playwright-cli -s=<name> delete-data             # 删除命名会话数据

⚠️ 会话保持特性:
  - 默认会话中Cookie和状态自动保持
  - 使用 --persistent 参数保存到磁盘
  - 使用 -s=name 创建隔离的命名会话

示例:
  playwright-cli open https://example.com                          # 默认会话
  playwright-cli -s=project1 open https://example.com --persistent  # 命名会话
  playwright-cli -s=project1 goto https://example.com/admin         # 继续同一会话
  playwright-cli list                                               # 查看所有会话
""",
        "return_format": {"type": "text"},
    },
}
