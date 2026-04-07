# Tools Catalog
## Available Tools
### 1. quick_nmap_scan
- **用途**：快速扫描常用端口
- **参数**：target (必填)
- **输出**：开放端口列表及服务信息
- **超时**：120秒
### 2. nmap_port_scanner
- **用途**：通用 nmap 扫描
- **参数**：
  - target (必填)：目标 IP 或域名
  - ports (可选)：端口范围
  - scan_type (可选)：扫描类型
  - extra_args (可选)：额外参数
- **超时**：300秒
### 3. full_nmap_scan
- **用途**：全面扫描（含 OS 检测和漏洞脚本）
- **参数**：target (必填)
- **超时**：600秒