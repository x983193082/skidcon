"""报告生成器 - 生成结构化渗透测试报告"""

import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import asdict

from core.test_state import TestState


class ReportGenerator:
    """渗透测试报告生成器"""

    SEVERITY_COLORS = {
        "critical": "#dc3545",
        "high": "#fd7e14",
        "medium": "#ffc107",
        "low": "#28a745",
        "info": "#17a2b8",
    }

    SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]

    def generate(self, state: TestState) -> str:
        """生成JSON格式报告"""
        report = {
            "report_info": {
                "generated_at": datetime.now().isoformat(),
                "tool": "SkidCon - AI Penetration Testing Assistant",
                "version": "1.0",
            },
            "executive_summary": self._generate_executive_summary(state),
            "target_info": {
                "target": state.target,
                "start_time": state.start_time.isoformat()
                if state.start_time
                else None,
                "end_time": state.end_time.isoformat() if state.end_time else None,
                "duration": self._calculate_duration(state),
            },
            "findings": {
                "hosts": self._format_hosts(state),
                "services": self._format_services(state),
                "vulnerabilities": self._format_vulnerabilities(state),
                "credentials": self._format_credentials(state),
            },
            "statistics": {
                "total_steps": len(state.executed_steps),
                "hosts_discovered": len(state.discovered_hosts),
                "services_discovered": len(state.discovered_services),
                "vulnerabilities_found": len(state.discovered_vulns),
                "credentials_found": len(state.discovered_creds),
                "phases_completed": len(set(s.phase for s in state.executed_steps)),
            },
            "timeline": self._generate_timeline(state),
            "recommendations": self._generate_recommendations(state),
        }

        return json.dumps(report, indent=2, ensure_ascii=False)

    def generate_markdown(self, state: TestState) -> str:
        """生成Markdown格式报告"""
        md = []

        md.append("# 渗透测试报告")
        md.append("")
        md.append(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        md.append(f"**工具**: SkidCon - AI渗透测试助手")
        md.append("")

        md.append("---")
        md.append("")

        md.append("## 1. 执行摘要")
        md.append("")
        md.append(self._generate_executive_summary(state))
        md.append("")

        md.append("## 2. 目标信息")
        md.append("")
        md.append(f"- **目标**: `{state.target}`")
        md.append(
            f"- **开始时间**: {state.start_time.strftime('%Y-%m-%d %H:%M:%S') if state.start_time else 'N/A'}"
        )
        md.append(
            f"- **结束时间**: {state.end_time.strftime('%Y-%m-%d %H:%M:%S') if state.end_time else 'N/A'}"
        )
        md.append(f"- **持续时间**: {self._calculate_duration(state)}")
        md.append("")

        md.append("## 3. 发现摘要")
        md.append("")
        md.append(f"| 类型 | 数量 |")
        md.append("|------|------|")
        md.append(f"| 主机 | {len(state.discovered_hosts)} |")
        md.append(f"| 服务 | {len(state.discovered_services)} |")
        md.append(f"| 漏洞 | {len(state.discovered_vulns)} |")
        md.append(f"| 凭据 | {len(state.discovered_creds)} |")
        md.append("")

        if state.discovered_hosts:
            md.append("### 3.1 发现的主机")
            md.append("")
            md.append("| IP地址 |")
            md.append("|--------|")
            for host in state.discovered_hosts:
                md.append(f"| `{host}` |")
            md.append("")

        if state.discovered_services:
            md.append("### 3.2 发现的服务")
            md.append("")
            md.append("| 主机 | 端口 | 服务 | 版本 |")
            md.append("|------|------|------|------|")
            for svc in state.discovered_services:
                md.append(
                    f"| `{svc.host}` | {svc.port} | {svc.service} | {svc.version or '-'} |"
                )
            md.append("")

        if state.discovered_vulns:
            md.append("### 3.3 发现的漏洞")
            md.append("")
            md.append("| 漏洞名称 | 严重程度 | 证据 |")
            md.append("|----------|----------|------|")
            for vuln in sorted(
                state.discovered_vulns,
                key=lambda v: self.SEVERITY_ORDER.index(v.severity)
                if v.severity in self.SEVERITY_ORDER
                else 5,
            ):
                md.append(
                    f"| {vuln.name} | **{vuln.severity.upper()}** | {vuln.evidence[:50] if vuln.evidence else '-'}... |"
                )
            md.append("")

        if state.discovered_creds:
            md.append("### 3.4 发现的凭据")
            md.append("")
            md.append("| 用户名 | 密码/哈希 | 来源 |")
            md.append("|--------|-----------|------|")
            for cred in state.discovered_creds:
                secret = cred.password or (cred.hash[:20] + "..." if cred.hash else "-")
                md.append(f"| `{cred.username}` | `{secret}` | {cred.source or '-'} |")
            md.append("")

        md.append("## 4. 测试时间线")
        md.append("")
        md.append("| 步骤 | 阶段 | 操作 | 结果 |")
        md.append("|------|------|------|------|")
        for step in state.executed_steps:
            result_summary = (
                step.result_summary[:50] + "..."
                if len(step.result_summary) > 50
                else step.result_summary
            )
            md.append(
                f"| {step.step} | {step.phase} | {step.query[:40]}... | {'✅' if step.verified else '❌'} {result_summary} |"
            )
        md.append("")

        md.append("## 5. 修复建议")
        md.append("")
        recommendations = self._generate_recommendations(state)
        for i, rec in enumerate(recommendations, 1):
            md.append(f"{i}. **{rec['title']}** ({rec['priority']}优先级)")
            md.append(f"   - {rec['description']}")
            md.append(f"   - 建议: {rec['recommendation']}")
            md.append("")

        md.append("---")
        md.append("")
        md.append("*本报告由 SkidCon 自动生成*")
        md.append("")

        return "\n".join(md)

    def _generate_executive_summary(self, state: TestState) -> str:
        """生成执行摘要"""
        total_vulns = len(state.discovered_vulns)
        critical_vulns = len(
            [v for v in state.discovered_vulns if v.severity == "critical"]
        )
        high_vulns = len([v for v in state.discovered_vulns if v.severity == "high"])

        summary_parts = []

        summary_parts.append(
            f"本次渗透测试针对目标 **{state.target}** 进行了全面的安全评估。"
        )

        summary_parts.append(
            f"测试共执行了 **{len(state.executed_steps)}** 个测试步骤，"
            f"完成了 **{len(set(s.phase for s in state.executed_steps))}** 个测试阶段。"
        )

        if state.discovered_hosts:
            summary_parts.append(f"发现了 **{len(state.discovered_hosts)}** 台主机。")

        if state.discovered_services:
            summary_parts.append(
                f"识别了 **{len(state.discovered_services)}** 个开放服务。"
            )

        if total_vulns > 0:
            severity_breakdown = []
            for sev in ["critical", "high", "medium", "low"]:
                count = len([v for v in state.discovered_vulns if v.severity == sev])
                if count > 0:
                    severity_breakdown.append(f"{count}个{sev.upper()}")

            summary_parts.append(
                f"共发现 **{total_vulns}** 个安全漏洞（{', '.join(severity_breakdown)}）。"
            )

            if critical_vulns > 0:
                summary_parts.append(
                    f"⚠️ **警告**: 发现 {critical_vulns} 个严重漏洞，需要立即修复！"
                )

        if state.discovered_creds:
            summary_parts.append(
                f"获取了 **{len(state.discovered_creds)}** 组凭据信息。"
            )

        if total_vulns == 0:
            summary_parts.append("在本次测试范围内未发现明显安全漏洞。")

        return " ".join(summary_parts)

    def _calculate_duration(self, state: TestState) -> str:
        """计算测试持续时间"""
        if not state.start_time or not state.end_time:
            return "N/A"

        delta = state.end_time - state.start_time

        hours = delta.seconds // 3600
        minutes = (delta.seconds % 3600) // 60
        seconds = delta.seconds % 60

        if hours > 0:
            return f"{hours}小时{minutes}分钟"
        elif minutes > 0:
            return f"{minutes}分钟{seconds}秒"
        else:
            return f"{seconds}秒"

    def _format_hosts(self, state: TestState) -> List[Dict[str, Any]]:
        """格式化主机列表"""
        return [{"ip": host} for host in state.discovered_hosts]

    def _format_services(self, state: TestState) -> List[Dict[str, Any]]:
        """格式化服务列表"""
        return [
            {
                "host": svc.host,
                "port": svc.port,
                "service": svc.service,
                "version": svc.version,
                "banner": svc.banner,
            }
            for svc in state.discovered_services
        ]

    def _format_vulnerabilities(self, state: TestState) -> List[Dict[str, Any]]:
        """格式化漏洞列表"""
        return [
            {
                "name": vuln.name,
                "severity": vuln.severity,
                "host": vuln.host,
                "port": vuln.port,
                "description": vuln.description,
                "evidence": vuln.evidence,
                "cve": vuln.cve,
            }
            for vuln in sorted(
                state.discovered_vulns,
                key=lambda v: self.SEVERITY_ORDER.index(v.severity)
                if v.severity in self.SEVERITY_ORDER
                else 5,
            )
        ]

    def _format_credentials(self, state: TestState) -> List[Dict[str, Any]]:
        """格式化凭据列表"""
        return [
            {
                "username": cred.username,
                "has_password": cred.password is not None,
                "has_hash": cred.hash is not None,
                "service": cred.service,
                "source": cred.source,
            }
            for cred in state.discovered_creds
        ]

    def _generate_timeline(self, state: TestState) -> List[Dict[str, Any]]:
        """生成测试时间线"""
        timeline = []

        for step in state.executed_steps:
            timeline.append(
                {
                    "step": step.step,
                    "phase": step.phase,
                    "action": step.query,
                    "verified": step.verified,
                    "timestamp": step.timestamp.isoformat() if step.timestamp else None,
                }
            )

        return timeline

    def _generate_recommendations(self, state: TestState) -> List[Dict[str, str]]:
        """生成修复建议"""
        recommendations = []

        for vuln in state.discovered_vulns:
            rec = self._get_vulnerability_recommendation(vuln)
            if rec and not any(r["title"] == rec["title"] for r in recommendations):
                recommendations.append(rec)

        if not recommendations:
            if state.discovered_services:
                for svc in state.discovered_services:
                    if svc.service.lower() in ["ssh", "telnet", "ftp"]:
                        recommendations.append(
                            {
                                "title": f"加固{svc.service.upper()}服务",
                                "priority": "高",
                                "description": f"发现开放{svc.service.upper()}服务（端口{svc.port}）",
                                "recommendation": "使用强密码、禁用root登录、使用密钥认证",
                            }
                        )

        if not recommendations:
            recommendations.append(
                {
                    "title": "定期安全评估",
                    "priority": "中",
                    "description": "建议定期进行渗透测试和安全评估",
                    "recommendation": "建立安全基线，定期执行漏洞扫描和渗透测试",
                }
            )

        return recommendations[:10]

    def _get_vulnerability_recommendation(self, vuln) -> Dict[str, str]:
        """根据漏洞类型生成修复建议"""
        vuln_type = vuln.name.lower()

        recommendations_map = {
            "sqli": {
                "title": "修复SQL注入漏洞",
                "priority": "严重",
                "description": "发现SQL注入漏洞，可能导致数据库被完全控制",
                "recommendation": "使用参数化查询、输入验证、最小权限原则",
            },
            "xss": {
                "title": "修复跨站脚本漏洞",
                "priority": "高",
                "description": "发现XSS漏洞，可能导致用户会话被劫持",
                "recommendation": "对所有输出进行HTML编码、使用CSP策略",
            },
            "rce": {
                "title": "修复远程代码执行漏洞",
                "priority": "严重",
                "description": "发现RCE漏洞，服务器可能被完全控制",
                "recommendation": "升级软件版本、禁用危险函数、使用WAF",
            },
            "default_creds": {
                "title": "修改默认凭据",
                "priority": "高",
                "description": "发现使用默认凭据的服务",
                "recommendation": "立即修改默认密码，使用强密码策略",
            },
        }

        for key, rec in recommendations_map.items():
            if key in vuln_type:
                return rec

        return {
            "title": f"修复{vuln.name}",
            "priority": "高" if vuln.severity in ["critical", "high"] else "中",
            "description": f"发现{vuln.severity}级别漏洞: {vuln.name}",
            "recommendation": "详细分析漏洞成因，应用适当的安全补丁或配置更改",
        }


report_generator = ReportGenerator()
