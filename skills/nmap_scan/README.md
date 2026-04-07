# Nmap Scan Skill
渗透测试信息收集阶段的端口扫描工具集。
## 快速开始
```python
from skills.nmap_scan import nmap_tool, quick_nmap_tool, full_nmap_tool
# 快速扫描
result = quick_nmap_tool.run(target="192.168.1.1")
# 标准扫描
result = nmap_tool.run(target="192.168.1.1", ports="1-1000", scan_type="-sV")
# 全面扫描
result = full_nmap_tool.run(target="192.168.1.1")
扫描模式
模式	    用途	        工具
快速扫描	初步信息收集	quick_nmap_scan
标准扫描	常规端口扫描	nmap_port_scanner
全面扫描	深度渗透测试	full_nmap_scan
文档
- SKILL.md (./SKILL.md) - 完整指令
- tools_catalog (./references/tools_catalog.md) - 工具目录
- installation (./references/installation.md) - 安装说明
---