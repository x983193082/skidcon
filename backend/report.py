"""
SkidCon 报告生成模块
生成 Markdown 格式的渗透测试报告，包含攻击路径、风险矩阵等增强内容
"""

import json
from datetime import datetime
from typing import Dict, Optional, List
from config import REPORTS_DIR


class ReportGenerator:
    """报告生成器"""
    
    def __init__(self):
        self.reports_dir = REPORTS_DIR
    
    def generate_report(self, task_id: str, target: str, results: Dict) -> str:
        """生成渗透测试报告"""
        vulnerabilities = self._extract_vulnerabilities(results)
        risk_rating = self._calculate_risk_rating(vulnerabilities)
        discovered_services = results.get("discovered_services", [])
        attack_paths = self._generate_attack_paths(vulnerabilities, discovered_services)
        
        report = self._build_report(
            task_id=task_id,
            target=target,
            results=results,
            vulnerabilities=vulnerabilities,
            risk_rating=risk_rating,
            discovered_services=discovered_services,
            attack_paths=attack_paths
        )
        
        report_path = self.reports_dir / f"{task_id}.md"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
        
        return str(report_path)
    
    def _extract_vulnerabilities(self, results: Dict) -> list:
        """从结果中提取漏洞信息"""
        vulns = []
        vuln_detection = results.get("stages", {}).get("vulnerability_detection", {})
        
        for tool_name, tool_result in vuln_detection.items():
            if tool_name == "analyzer_report" or not isinstance(tool_result, dict):
                continue
                
            parsed_data = tool_result.get("parsed_data", {})
            
            if tool_name == "sqlmap" and parsed_data.get("vulnerable"):
                vulns.append({
                    "name": "SQL 注入漏洞",
                    "severity": "Critical",
                    "tool": "sqlmap",
                    "description": "目标存在 SQL 注入漏洞，攻击者可以执行任意 SQL 查询",
                    "evidence": tool_result.get("raw_output", "")[:500],
                    "remediation": "使用参数化查询或预编译语句，避免直接拼接用户输入",
                    "cvss_score": 9.8,
                    "exploitability": "高",
                })
            
            if tool_name == "nuclei" and isinstance(parsed_data, dict):
                for vuln in parsed_data.get("vulnerabilities", []):
                    severity = vuln.get("severity", "Medium")
                    cvss_map = {"critical": 9.8, "high": 7.5, "medium": 5.0, "low": 3.0, "info": 0.0}
                    vulns.append({
                        "name": vuln.get("name", vuln.get("template", "未知漏洞")),
                        "severity": severity.capitalize(),
                        "tool": "nuclei",
                        "description": vuln.get("name", ""),
                        "evidence": json.dumps(vuln, ensure_ascii=False)[:500],
                        "remediation": f"根据 {vuln.get('template', '该漏洞')} 的修复建议进行修复",
                        "cvss_score": cvss_map.get(severity.lower(), 5.0),
                        "exploitability": "高" if severity.lower() in ["critical", "high"] else "中",
                        "cve": vuln.get("cve", []),
                        "reference": vuln.get("reference", []),
                    })
            
            if tool_name == "nikto" and isinstance(parsed_data, dict):
                for vuln_line in parsed_data.get("vulnerabilities", []):
                    vulns.append({
                        "name": "Web 配置问题",
                        "severity": "Medium",
                        "tool": "nikto",
                        "description": vuln_line,
                        "evidence": vuln_line,
                        "remediation": "检查并修复 Web 服务器配置",
                        "cvss_score": 5.0,
                        "exploitability": "低",
                    })
        
        exploitation = results.get("stages", {}).get("exploitation", {})
        for key, value in exploitation.items():
            if key.startswith("exploit_plan_") and isinstance(value, dict):
                vulns.append({
                    "name": f"[潜在] {value.get('vuln_name', '未知漏洞')}",
                    "severity": value.get("severity", "Medium"),
                    "tool": "exploitation_analysis",
                    "description": f"漏洞利用方案：{value.get('notes', '')}",
                    "evidence": json.dumps(value.get("exploitation_steps", []), ensure_ascii=False),
                    "remediation": "建议立即修复该漏洞",
                    "cvss_score": 7.0,
                    "exploitability": value.get("risk_level", "中"),
                })
        
        if not vulns:
            vulns.append({
                "name": "需要人工验证",
                "severity": "Info",
                "tool": "manual",
                "description": "自动扫描未发现明显漏洞，建议进行人工渗透测试",
                "evidence": "",
                "remediation": "定期进行安全审计和渗透测试",
                "cvss_score": 0.0,
                "exploitability": "无",
            })
        
        return vulns
    
    def _calculate_risk_rating(self, vulnerabilities: list) -> str:
        """计算整体风险评级"""
        if not vulnerabilities:
            return "Low"
        
        severity_scores = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1, "Info": 0}
        max_score = max((severity_scores.get(v.get("severity", "Low"), 0) for v in vulnerabilities), default=0)
        
        if max_score >= 4: return "Critical"
        elif max_score >= 3: return "High"
        elif max_score >= 2: return "Medium"
        else: return "Low"
    
    def _generate_attack_paths(self, vulnerabilities: List[Dict], services: List[Dict]) -> List[Dict]:
        """生成可能的攻击路径"""
        paths = []
        critical_vulns = [v for v in vulnerabilities if v.get("severity") in ["Critical", "High"]]
        
        if critical_vulns:
            paths.append({
                "name": "直接漏洞利用路径",
                "description": "通过已知高危漏洞直接获取系统访问权限",
                "steps": ["1. 信息收集：识别目标系统和服务", f"2. 漏洞利用：利用 {critical_vulns[0]['name']} 获取初始访问权限", "3. 权限提升：尝试获取更高权限", "4. 横向移动：访问其他系统或服务", "5. 数据提取：获取敏感数据"],
                "difficulty": "低",
                "impact": "严重",
                "mitigation": "立即修复高危漏洞"
            })
        
        service_types = [s.get("service", "").lower() for s in services]
        
        if "http" in service_types or "https" in service_types:
            paths.append({
                "name": "Web 应用攻击路径",
                "description": "通过 Web 应用漏洞获取系统访问权限",
                "steps": ["1. 信息收集：识别 Web 应用技术和框架", "2. 漏洞扫描：检测 SQL 注入、XSS、文件上传等漏洞", "3. 漏洞利用：利用 Web 漏洞获取 Web Shell", "4. 权限提升：从 Web 用户提升到系统用户", "5. 横向移动：访问内网其他系统"],
                "difficulty": "中",
                "impact": "高",
                "mitigation": "加强 Web 应用安全，定期扫描漏洞"
            })
        
        if "ssh" in service_types:
            paths.append({
                "name": "SSH 暴力破解路径",
                "description": "通过 SSH 弱口令获取系统访问权限",
                "steps": ["1. 信息收集：确认 SSH 服务开放", "2. 用户枚举：尝试获取有效用户名", "3. 密码爆破：使用字典攻击尝试登录", "4. 权限提升：获取 root 权限", "5. 持久化：安装后门或创建新用户"],
                "difficulty": "中",
                "impact": "高",
                "mitigation": "禁用密码登录，使用密钥认证，限制登录 IP"
            })
        
        if "smb" in service_types or "microsoft-ds" in service_types:
            paths.append({
                "name": "SMB/Windows 域攻击路径",
                "description": "通过 SMB 服务或 Windows 域漏洞获取访问权限",
                "steps": ["1. 信息收集：枚举 SMB 共享和用户", "2. 漏洞检测：检测 EternalBlue 等已知漏洞", "3. 漏洞利用：利用 SMB 漏洞获取访问权限", "4. 域渗透：尝试获取域控制器权限", "5. 横向移动：访问域内其他系统"],
                "difficulty": "中",
                "impact": "严重",
                "mitigation": "及时更新系统补丁，禁用不必要的 SMB 功能"
            })
        
        return paths
    
    def _build_report(self, task_id: str, target: str, results: Dict, vulnerabilities: list, risk_rating: str, discovered_services: List[Dict], attack_paths: List[Dict]) -> str:
        """构建 Markdown 报告"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        stages = results.get("stages", {})
        recon = stages.get("recon", {})
        service_analysis = stages.get("service_analysis", {})
        vuln_detection = stages.get("vulnerability_detection", {})
        exploitation = stages.get("exploitation", {})
        
        report = f"""# SkidCon 渗透测试报告

## 基本信息

| 项目 | 内容 |
|------|------|
| 任务 ID | {task_id} |
| 测试目标 | {target} |
| 测试时间 | {now} |
| 风险评级 | **{risk_rating}** |
| 发现漏洞数 | {len(vulnerabilities)} |
| 发现服务数 | {len(discovered_services)} |

---

## 1. 执行摘要

本次渗透测试针对目标 **{target}** 进行了全面的安全评估。测试采用多阶段链式攻击方法，包括信息收集、服务分析、漏洞检测和漏洞利用分析。

### 1.1 测试范围

- 端口扫描和服务识别
- Web 应用程序安全测试
- 已知漏洞扫描
- 配置安全检查
- 漏洞利用方案分析

### 1.2 发现概览

| 风险等级 | 数量 |
|----------|------|
| Critical | {sum(1 for v in vulnerabilities if v['severity'] == 'Critical')} |
| High | {sum(1 for v in vulnerabilities if v['severity'] == 'High')} |
| Medium | {sum(1 for v in vulnerabilities if v['severity'] == 'Medium')} |
| Low | {sum(1 for v in vulnerabilities if v['severity'] == 'Low')} |
| Info | {sum(1 for v in vulnerabilities if v['severity'] == 'Info')} |

### 1.3 风险评级说明

- **Critical**: 存在可直接利用的高危漏洞，可能导致系统完全被控制
- **High**: 存在严重安全问题，可能导致敏感数据泄露
- **Medium**: 存在中等风险问题，需要关注并及时修复
- **Low**: 存在低风险问题，建议在后续版本中修复
- **Info**: 信息性发现，无需立即修复

---

## 2. 攻击面分析

### 2.1 开放服务

"""
        
        if discovered_services:
            report += "| 端口 | 协议 | 服务 | 版本 |\n|------|------|------|------|\n"
            for service in discovered_services:
                report += f"| {service.get('port', 'N/A')} | tcp | {service.get('service', 'unknown')} | {service.get('version', '')} |\n"
        else:
            report += "未发现开放服务或服务信息不可用。\n"
        
        report += "\n### 2.2 技术栈识别\n\n"
        whatweb_result = recon.get("whatweb", {})
        if whatweb_result.get("parsed_data", {}).get("technologies"):
            techs = whatweb_result["parsed_data"]["technologies"]
            report += "识别到的技术栈：\n\n"
            for tech in techs[:10]:
                report += f"- {tech}\n"
        else:
            report += "未识别到具体技术栈信息。\n"
        
        report += "\n---\n\n## 3. 漏洞详情\n\n"
        
        severity_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}
        sorted_vulns = sorted(vulnerabilities, key=lambda v: severity_order.get(v.get("severity", "Info"), 5))
        
        for idx, vuln in enumerate(sorted_vulns, 1):
            cve_info = ""
            if vuln.get("cve"):
                cve_list = vuln["cve"] if isinstance(vuln["cve"], list) else [vuln["cve"]]
                cve_info = f"\n\n**CVE 编号**: {', '.join([c for c in cve_list if c])}"
            
            reference_info = ""
            if vuln.get("reference"):
                ref_list = vuln["reference"] if isinstance(vuln["reference"], list) else [vuln["reference"]]
                reference_info = "\n\n**参考链接**:\n"
                for ref in ref_list[:3]:
                    reference_info += f"- {ref}\n"
            
            report += f"""### 3.{idx} {vuln['name']} - {vuln['severity']}

**风险等级**: {vuln['severity']}

**CVSS 评分**: {vuln.get('cvss_score', 'N/A')}

**检测工具**: {vuln['tool']}

**可利用性**: {vuln.get('exploitability', '未知')}{cve_info}

**漏洞描述**: 
{vuln['description']}

**影响范围**: 
该漏洞可能被攻击者利用来获取未授权访问、执行任意代码或窃取敏感数据。

**证据**: 
```
{vuln['evidence'][:300] if vuln['evidence'] else '无'}
```

**修复建议**: 
{vuln['remediation']}{reference_info}

---

"""
        
        report += "## 4. 攻击路径分析\n\n"
        
        if attack_paths:
            for idx, path in enumerate(attack_paths, 1):
                report += f"""### 4.{idx} {path['name']}

**描述**: {path['description']}

**利用难度**: {path['difficulty']}

**潜在影响**: {path['impact']}

**攻击步骤**:
"""
                for step in path["steps"]:
                    report += f"\n{step}"
                report += f"\n\n**缓解措施**: {path['mitigation']}\n\n---\n\n"
        else:
            report += "未发现明显的攻击路径。\n\n---\n\n"
        
        report += "## 5. 修复建议\n\n### 5.1 紧急修复（Critical/High）\n\n"
        critical_high = [v for v in vulnerabilities if v.get("severity") in ["Critical", "High"]]
        if critical_high:
            for idx, vuln in enumerate(critical_high, 1):
                report += f"{idx}. **{vuln['name']}**: {vuln['remediation']}\n"
        else:
            report += "无紧急修复项。\n"
        
        report += "\n### 5.2 计划修复（Medium）\n\n"
        medium = [v for v in vulnerabilities if v.get("severity") == "Medium"]
        if medium:
            for idx, vuln in enumerate(medium, 1):
                report += f"{idx}. **{vuln['name']}**: {vuln['remediation']}\n"
        else:
            report += "无计划修复项。\n"
        
        report += "\n### 5.3 建议改进（Low/Info）\n\n"
        low_info = [v for v in vulnerabilities if v.get("severity") in ["Low", "Info"]]
        if low_info:
            for idx, vuln in enumerate(low_info, 1):
                report += f"{idx}. **{vuln['name']}**: {vuln['remediation']}\n"
        else:
            report += "无建议改进项。\n"
        
        report += """
---

## 6. 附录

### 6.1 测试工具列表

| 工具名称 | 用途 | 类别 |
|----------|------|------|
| Nmap | 端口扫描和服务识别 | 扫描 |
| SQLMap | SQL 注入检测 | Web |
| Nuclei | 漏洞扫描 | 漏洞利用 |
| Nikto | Web 漏洞扫描 | Web |
| Searchsploit | 漏洞数据库查询 | 漏洞利用 |
| Subfinder | 子域名发现 | 信息收集 |
| WhatWeb | 技术栈识别 | 信息收集 |
| Whois | 域名信息查询 | 信息收集 |
| Dig | DNS 查询 | 信息收集 |
| Enum4linux | SMB 枚举 | 服务枚举 |
| Gobuster | 目录爆破 | Web |
| Hydra | 密码爆破 | 密码攻击 |

### 6.2 测试方法

本次测试遵循以下方法论：

1. **PTES** (Penetration Testing Execution Standard)
2. **OWASP Testing Guide**
3. **NIST SP 800-115**

### 6.3 测试阶段执行详情

#### 阶段 1: 信息收集

"""
        for tool_name, tool_result in recon.items():
            if tool_name != "planner_analysis" and isinstance(tool_result, dict):
                exec_time = tool_result.get("execution_time", 0)
                success = "✅" if tool_result.get("success") else "❌"
                report += f"- {success} **{tool_name}**: 执行时间 {exec_time:.2f}s\n"
        
        report += "\n#### 阶段 2: 服务分析\n\n"
        for tool_name, tool_result in service_analysis.items():
            if isinstance(tool_result, dict):
                exec_time = tool_result.get("execution_time", 0)
                success = "✅" if tool_result.get("success") else "❌"
                report += f"- {success} **{tool_name}**: 执行时间 {exec_time:.2f}s\n"
        
        report += "\n#### 阶段 3: 漏洞检测\n\n"
        for tool_name, tool_result in vuln_detection.items():
            if tool_name != "analyzer_report" and isinstance(tool_result, dict):
                exec_time = tool_result.get("execution_time", 0)
                success = "✅" if tool_result.get("success") else "❌"
                report += f"- {success} **{tool_name}**: 执行时间 {exec_time:.2f}s\n"
        
        report += "\n#### 阶段 4: 漏洞利用分析\n\n"
        exploit_summary = exploitation.get("exploitation_summary", {})
        report += f"- 分析漏洞数: {exploit_summary.get('total_vulns_analyzed', 0)}\n"
        report += f"- 发现 Exploit: {exploit_summary.get('exploits_found', 0)}\n"
        
        report += f"""
### 6.4 免责声明

本报告仅供授权的安全测试使用。未经授权的渗透测试可能违反相关法律法规。
测试人员应确保已获得目标系统所有者的明确书面授权。

---

*报告生成时间: {now}*
*SkidCon AI 渗透测试系统 v1.0.0*
"""
        
        return report
    
    def get_report(self, task_id: str) -> Optional[str]:
        """获取已有报告"""
        report_path = self.reports_dir / f"{task_id}.md"
        if report_path.exists():
            with open(report_path, "r", encoding="utf-8") as f:
                return f.read()
        return None
    
    def list_reports(self) -> List[Dict]:
        """列出所有报告"""
        reports = []
        for report_file in self.reports_dir.glob("*.md"):
            reports.append({
                "task_id": report_file.stem,
                "filename": report_file.name,
                "size": report_file.stat().st_size,
                "modified": datetime.fromtimestamp(report_file.stat().st_mtime).isoformat()
            })
        return reports


report_generator = ReportGenerator()
