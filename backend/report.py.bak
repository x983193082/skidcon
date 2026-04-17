"""
SkidCon 报告生成模块
生成 Markdown 格式的渗透测试报告
"""

import json
from datetime import datetime
from typing import Dict, Optional
from config import REPORTS_DIR


class ReportGenerator:
    """报告生成器"""
    
    def __init__(self):
        self.reports_dir = REPORTS_DIR
    
    def generate_report(self, task_id: str, target: str, results: Dict) -> str:
        """生成渗透测试报告"""
        
        # 提取关键信息
        vulnerabilities = self._extract_vulnerabilities(results)
        risk_rating = self._calculate_risk_rating(vulnerabilities)
        
        # 生成报告内容
        report = self._build_report(
            task_id=task_id,
            target=target,
            results=results,
            vulnerabilities=vulnerabilities,
            risk_rating=risk_rating
        )
        
        # 保存报告
        report_path = self.reports_dir / f"{task_id}.md"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report)
        
        return str(report_path)
    
    def _extract_vulnerabilities(self, results: Dict) -> list:
        """从结果中提取漏洞信息"""
        vulns = []
        
        # 从漏洞检测阶段提取
        vuln_detection = results.get("stages", {}).get("vulnerability_detection", {})
        
        # 从分析器报告中提取
        analyzer_report = vuln_detection.get("analyzer_report", "")
        
        # 从工具结果中提取
        for tool_name, tool_result in vuln_detection.items():
            if tool_name == "analyzer_report":
                continue
            
            parsed_data = tool_result.get("parsed_data", {})
            
            # SQLMap 结果
            if tool_name == "sqlmap" and parsed_data.get("vulnerable"):
                vulns.append({
                    "name": "SQL 注入漏洞",
                    "severity": "Critical",
                    "tool": "sqlmap",
                    "description": "目标存在 SQL 注入漏洞，攻击者可以执行任意 SQL 查询",
                    "evidence": tool_result.get("raw_output", "")[:500],
                    "remediation": "使用参数化查询或预编译语句，避免直接拼接用户输入"
                })
            
            # Nuclei 结果
            if tool_name == "nuclei":
                for vuln in parsed_data.get("vulnerabilities", []):
                    vulns.append({
                        "name": vuln.get("template-id", "未知漏洞"),
                        "severity": vuln.get("info", {}).get("severity", "Medium"),
                        "tool": "nuclei",
                        "description": vuln.get("info", {}).get("name", ""),
                        "evidence": json.dumps(vuln, ensure_ascii=False)[:500],
                        "remediation": "根据具体漏洞类型应用相应的修复措施"
                    })
            
            # Nikto 结果
            if tool_name == "nikto":
                for vuln_line in parsed_data.get("vulnerabilities", []):
                    vulns.append({
                        "name": "Web 配置问题",
                        "severity": "Medium",
                        "tool": "nikto",
                        "description": vuln_line,
                        "evidence": vuln_line,
                        "remediation": "检查并修复 Web 服务器配置"
                    })
        
        # 如果没有自动提取到漏洞，添加一个默认条目
        if not vulns:
            vulns.append({
                "name": "需要人工验证",
                "severity": "Info",
                "tool": "manual",
                "description": "自动扫描未发现明显漏洞，建议进行人工渗透测试",
                "evidence": "",
                "remediation": "定期进行安全审计和渗透测试"
            })
        
        return vulns
    
    def _calculate_risk_rating(self, vulnerabilities: list) -> str:
        """计算整体风险评级"""
        if not vulnerabilities:
            return "Low"
        
        severity_scores = {
            "Critical": 4,
            "High": 3,
            "Medium": 2,
            "Low": 1,
            "Info": 0
        }
        
        max_score = 0
        for vuln in vulnerabilities:
            score = severity_scores.get(vuln.get("severity", "Low"), 0)
            max_score = max(max_score, score)
        
        if max_score >= 4:
            return "Critical"
        elif max_score >= 3:
            return "High"
        elif max_score >= 2:
            return "Medium"
        else:
            return "Low"
    
    def _build_report(self, task_id: str, target: str, results: Dict, 
                     vulnerabilities: list, risk_rating: str) -> str:
        """构建 Markdown 报告"""
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        report = f"""# SkidCon 渗透测试报告

## 基本信息

| 项目 | 内容 |
|------|------|
| 任务 ID | {task_id} |
| 测试目标 | {target} |
| 测试时间 | {now} |
| 风险评级 | **{risk_rating}** |
| 发现漏洞数 | {len(vulnerabilities)} |

---

## 1. 执行摘要

本次渗透测试针对目标 **{target}** 进行了全面的安全评估。测试采用多阶段链式攻击方法，包括信息收集、服务分析、漏洞检测和漏洞利用。

### 测试范围

- 端口扫描和服务识别
- Web 应用程序安全测试
- 已知漏洞扫描
- 配置安全检查

### 发现概览

| 风险等级 | 数量 |
|----------|------|
| Critical | {sum(1 for v in vulnerabilities if v['severity'] == 'Critical')} |
| High | {sum(1 for v in vulnerabilities if v['severity'] == 'High')} |
| Medium | {sum(1 for v in vulnerabilities if v['severity'] == 'Medium')} |
| Low | {sum(1 for v in vulnerabilities if v['severity'] == 'Low')} |
| Info | {sum(1 for v in vulnerabilities if v['severity'] == 'Info')} |

### 风险评级说明

- **Critical**: 存在可直接利用的高危漏洞，可能导致系统完全被控制
- **High**: 存在严重安全问题，可能导致敏感数据泄露
- **Medium**: 存在中等风险问题，需要关注并及时修复
- **Low**: 存在低风险问题，建议在后续版本中修复
- **Info**: 信息性发现，无需立即修复

---

## 2. 漏洞详情

"""
        
        # 添加每个漏洞的详细信息
        for idx, vuln in enumerate(vulnerabilities, 1):
            report += f"""### 2.{idx} {vuln['name']} - {vuln['severity']}

**风险等级**: {vuln['severity']}

**检测工具**: {vuln['tool']}

**漏洞描述**: 
{vuln['description']}

**影响范围**: 
该漏洞可能被攻击者利用来获取未授权访问、执行任意代码或窃取敏感数据。

**证据**: 
```
{vuln['evidence'][:300] if vuln['evidence'] else '无'}
```

**修复建议**: 
{vuln['remediation']}

**参考链接**: 
- https://owasp.org/www-project-top-ten/
- https://cwe.mitre.org/

---

"""
        
        # 添加附录
        report += f"""## 3. 附录

### 3.1 测试工具列表

本次测试使用了以下安全工具：

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

### 3.2 测试方法

本次测试遵循以下方法论：

1. **PTES** (Penetration Testing Execution Standard)
2. **OWASP Testing Guide**
3. **NIST SP 800-115**

### 3.3 免责声明

本报告仅供授权的安全测试使用。未经授权的渗透测试可能违反相关法律法规。
测试人员应确保已获得目标系统所有者的明确书面授权。

### 3.4 联系方式

如有任何疑问或需要进一步的技术支持，请联系安全团队。

---

*报告由 SkidCon AI 渗透测试系统自动生成*
*生成时间: {now}*
"""
        
        return report
    
    def get_report(self, task_id: str) -> Optional[str]:
        """获取报告内容"""
        report_path = self.reports_dir / f"{task_id}.md"
        if report_path.exists():
            with open(report_path, "r", encoding="utf-8") as f:
                return f.read()
        return None
    
    def list_reports(self) -> list:
        """列出所有报告"""
        reports = []
        for report_file in self.reports_dir.glob("*.md"):
            reports.append({
                "task_id": report_file.stem,
                "filename": report_file.name,
                "created_at": datetime.fromtimestamp(report_file.stat().st_mtime).isoformat()
            })
        return sorted(reports, key=lambda x: x["created_at"], reverse=True)


# 全局报告生成器实例
report_generator = ReportGenerator()
