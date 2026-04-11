"""
Report Agent - 报告生成Agent
负责生成渗透测试报告
"""
from typing import Dict, Any, List
from datetime import datetime, timezone
from loguru import logger
from ..core.agent_interface import BaseAgent, AgentRole, AgentState


class ReportAgent(BaseAgent):
    """
    报告生成Agent

    职责：
    - 汇总所有发现
    - 计算风险评分
    - 生成执行摘要
    - 生成详细报告
    - 导出多种格式
    """

    SEVERITY_WEIGHTS = {
        "CRITICAL": 10.0,
        "HIGH": 8.0,
        "MEDIUM": 5.0,
        "LOW": 2.0,
        "INFO": 0.5,
        "UNKNOWN": 0.0
    }

    VULNERABILITY_RECOMMENDATIONS = {
        "sql_injection": "使用参数化查询,输入验证,Web应用防火墙",
        "xss": "输出编码,Content Security Policy,HTTPOnly Cookie",
        "rce": "禁用危险函数,最小权限原则,代码审计",
        "default_creds": "修改默认口令,强制密码策略,双因素认证",
        "unauth_access": "认证授权机制,IP白名单,API密钥",
        "deserialization": "不反序列化不可信数据,白名单,安全配置",
        "file_upload": "文件类型检测,存储分离,权限控制",
        "privilege_escalation": "最小权限,定期审计,监控告警"
    }

    def __init__(
        self,
        name: str = "ReportAgent",
        description: str = "负责生成渗透测试报告",
        config: Dict[str, Any] = None
    ):
        super().__init__(
            name=name,
            role=AgentRole.REPORT,
            description=description,
            config=config
        )
        self._output_formats = config.get("output_formats", ["json", "html"]) if config else ["json", "html"]

    async def execute(self, target: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """生成报告"""
        self.update_state(AgentState.RUNNING)
        context = context or {}

        result = {
            "target": target,
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "executive_summary": {},
            "findings": [],
            "vulnerabilities": [],
            "recommendations": [],
            "appendix": {}
        }

        try:
            logger.info("Step 1: Aggregating all findings")
            result["appendix"] = self._aggregate_findings(context)

            logger.info("Step 2: Calculating risk score")
            result["executive_summary"] = self._generate_executive_summary(context)

            logger.info("Step 3: Generating detailed report")
            result["findings"] = self._generate_findings(context)
            result["vulnerabilities"] = self._generate_vulnerabilities(context)
            result["recommendations"] = self._generate_recommendations(context)

            self.set_context(result)
            self.update_state(AgentState.COMPLETED)
            return result

        except Exception as e:
            self.update_state(AgentState.FAILED)
            logger.exception(f"Report generation failed: {e}")
            return {"target": target, "error": str(e), "success": False}

    def _aggregate_findings(self, context: Dict) -> Dict:
        """汇总所有发现"""
        exploit_data = context.get("exploit", {})
        privilege_data = context.get("privilege", {})

        return {
            "recon": context.get("recon", {}),
            "exploit": {
                "exploits": exploit_data.get("exploits", []),
                "successful": exploit_data.get("successful", []),
                "failed": exploit_data.get("failed", []),
                "shells": exploit_data.get("shells", []),
                "cve_results": exploit_data.get("cve_results", [])
            },
            "privilege": {
                "escalation_methods": privilege_data.get("escalation_methods", []),
                "persistence": privilege_data.get("persistence", []),
                "successful_escalation": privilege_data.get("successful_escalation", False),
                "final_privileges": privilege_data.get("final_privileges", [])
            }
        }

    def _generate_executive_summary(self, context: Dict) -> Dict:
        """生成执行摘要"""
        exploit_data = context.get("exploit", {})
        privilege_data = context.get("privilege", {})

        # 修正：正确从 exploit_data 中获取 cve_results
        cve_results = exploit_data.get("cve_results", [])

        total_findings = len(cve_results)
        critical = sum(1 for c in cve_results if c.get("severity") == "CRITICAL")
        high = sum(1 for c in cve_results if c.get("severity") == "HIGH")
        medium = sum(1 for c in cve_results if c.get("severity") == "MEDIUM")
        low = sum(1 for c in cve_results if c.get("severity") == "LOW")

        risk_score = self._calculate_risk_score(cve_results)

        shells_obtained = len(exploit_data.get("shells", []))
        escalation_success = privilege_data.get("successful_escalation", False)
        persistence_established = len(privilege_data.get("persistence", [])) > 0

        summary_text = self._generate_summary_text(
            total_findings, risk_score, shells_obtained, escalation_success
        )

        return {
            "total_findings": total_findings,
            "critical": critical,
            "high": high,
            "medium": medium,
            "low": low,
            "risk_score": risk_score,
            "shells_obtained": shells_obtained,
            "escalation_success": escalation_success,
            "persistence_established": persistence_established,
            "summary_text": summary_text
        }

    def _calculate_risk_score(self, findings: List[Dict]) -> float:
        """
        计算风险评分 (0-10)
        修正：仅使用自定义权重累加，并限制在 10.0 以内
        """
        if not findings:
            return 0.0

        total_weight = 0.0
        for finding in findings:
            severity = finding.get("severity", "UNKNOWN").upper()
            weight = self.SEVERITY_WEIGHTS.get(severity, 0.0)
            total_weight += weight

        # 简单限制最大值，也可考虑更复杂的归一化
        return round(min(total_weight, 10.0), 1)

    def _generate_summary_text(
        self,
        total_findings: int,
        risk_score: float,
        shells: int,
        escalated: bool
    ) -> str:
        """生成执行摘要文本"""
        lines = [
            f"渗透测试目标: 发现 {total_findings} 个安全问题,",
            f"综合风险评分: {risk_score:.1f}/10.0",
        ]

        if shells > 0:
            lines.append(f"成功获取 {shells} 个shell")
        if escalated:
            lines.append("权限提升成功")

        if risk_score >= 8.0:
            lines.append("建议优先修复关键问题")
        elif risk_score >= 5.0:
            lines.append("建议在计划周期内修复")
        else:
            lines.append("风险可控,建议持续监控")

        return " | ".join(lines)

    def _generate_findings(self, context: Dict) -> List[Dict]:
        """生成发现列表"""
        findings = []
        exploit_data = context.get("exploit", {})
        privilege_data = context.get("privilege", {})

        cve_results = exploit_data.get("cve_results", [])
        for cve in cve_results:
            finding = {
                "id": cve.get("cve_id", ""),
                "title": cve.get("description", "")[:100],
                "severity": cve.get("severity", "UNKNOWN"),
                "cvss": cve.get("cvss_score", 0.0),
                "source": cve.get("source", "unknown"),
                "service": cve.get("service", "")
            }
            findings.append(finding)

        if privilege_data.get("successful_escalation"):
            findings.append({
                "id": "PRIV-001",
                "title": "Privilege Escalation Successful",  # 修正拼写及多余空格
                "severity": "CRITICAL",
                "cvss": 10.0,
                "source": "privilege_agent"
            })

        return findings[:50]

    def _generate_vulnerabilities(self, context: Dict) -> List[Dict]:
        """生成漏洞列表"""
        vulnerabilities = []
        exploit_data = context.get("exploit", {})

        for cve in exploit_data.get("cve_results", []):
            vuln = {
                "cve_id": cve.get("cve_id", ""),
                "title": cve.get("description", "")[:150],
                "severity": cve.get("severity", "UNKNOWN"),
                "cvss_score": cve.get("cvss_score", 0.0),
                "description": cve.get("description", ""),
                "affected_service": cve.get("service", ""),
                "status": "identified"
            }
            vulnerabilities.append(vuln)

        return vulnerabilities

    def _generate_recommendations(self, context: Dict) -> List[Dict]:
        """生成建议列表"""
        recommendations = []
        exploit_data = context.get("exploit", {})
        privilege_data = context.get("privilege", {})

        cve_results = exploit_data.get("cve_results", [])
        seen_types = set()

        for cve in cve_results:
            cve_id = cve.get("cve_id", "")
            if not cve_id:
                continue

            for vuln_type, recommendation in self.VULNERABILITY_RECOMMENDATIONS.items():
                if vuln_type in cve_id.lower():
                    if vuln_type not in seen_types:
                        seen_types.add(vuln_type)
                        recommendations.append({
                            "category": vuln_type,
                            "recommendation": recommendation,
                            "priority": cve.get("severity", "UNKNOWN"),
                            "references": [cve_id]
                        })

        if privilege_data.get("successful_escalation"):
            recommendations.append({
                "category": "privilege_escalation",
                "recommendation": "审查用户权限,实施最小权限原则,加强监控",
                "priority": "HIGH",
                "references": ["privilege_escalation"]
            })

        if not recommendations:
            recommendations.append({
                "category": "general",
                "recommendation": "持续监控安全更新,定期渗透测试",
                "priority": "MEDIUM",
                "references": []
            })

        return recommendations

    def validate_result(self, result: Dict[str, Any]) -> bool:
        if not result:
            return False
        if "error" in result:
            return False
        return "generated_at" in result

    def report(self) -> Dict[str, Any]:
        ctx = self._context or {}
        return {
            "agent": self.name,
            "role": self.role.value,
            "state": self.state.value,
            "generated_at": ctx.get("generated_at"),
            "target": ctx.get("target"),
            "summary": ctx.get("executive_summary", {})
        }