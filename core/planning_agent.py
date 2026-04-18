"""规划Agent - 生成渗透测试计划"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass


@dataclass
class TestPhase:
    name: str
    description: str
    tools: List[str]
    objectives: List[str]


class PenetrationTestPlanner:
    """渗透测试规划器"""

    STANDARD_PHASES = [
        TestPhase(
            name="reconnaissance",
            description="信息收集阶段 - 发现目标和网络范围",
            tools=["nmap", "whois", "dnsrecon", "theharvester"],
            objectives=[
                "识别目标IP范围",
                "发现存活主机",
                "收集域名信息",
                "识别网络架构",
            ],
        ),
        TestPhase(
            name="scanning",
            description="扫描阶段 - 识别开放端口和服务",
            tools=["nmap", "masscan", "rustscan"],
            objectives=[
                "扫描开放端口",
                "识别服务版本",
                "识别操作系统",
                "发现潜在攻击面",
            ],
        ),
        TestPhase(
            name="enumeration",
            description="枚举阶段 - 详细收集服务信息",
            tools=["enum4linux", "nbtscan", "ldapsearch", "gobuster", "nikto"],
            objectives=[
                "枚举用户和组",
                "枚举共享资源",
                "枚举Web目录",
                "收集配置信息",
            ],
        ),
        TestPhase(
            name="vulnerability",
            description="漏洞识别阶段 - 发现可利用漏洞",
            tools=["nmap scripts", "searchsploit", "nikto", "wpscan"],
            objectives=[
                "扫描已知CVE",
                "识别配置弱点",
                "发现Web漏洞",
                "评估漏洞风险",
            ],
        ),
        TestPhase(
            name="exploitation",
            description="漏洞利用阶段 - 获取初始访问权限",
            tools=["metasploit", "searchsploit", "sqlmap", "hydra"],
            objectives=[
                "利用发现的漏洞",
                "获取shell访问",
                "提取凭据",
                "建立持久化",
            ],
        ),
        TestPhase(
            name="post_exploitation",
            description="后渗透阶段 - 扩大访问权限",
            tools=["linpeas", "winpeas", "mimikatz", "bloodhound"],
            objectives=[
                "权限提升",
                "横向移动",
                "数据提取",
                "清理痕迹",
            ],
        ),
        TestPhase(
            name="reporting",
            description="报告阶段 - 整理测试结果",
            tools=["自定义脚本"],
            objectives=[
                "生成测试报告",
                "总结发现",
                "提供修复建议",
            ],
        ),
    ]

    TARGET_TYPE_PATTERNS = {
        "ip": r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$",
        "ip_range": r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/\d{1,2}$",
        "domain": r"^[a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}$",
        "url": r"^https?://",
    }

    def __init__(self):
        self.llm_enabled = True

    def analyze_target(self, target: str) -> Dict[str, Any]:
        """分析目标类型"""
        import re

        target_type = "unknown"

        for t_type, pattern in self.TARGET_TYPE_PATTERNS.items():
            if re.match(pattern, target.strip()):
                target_type = t_type
                break

        return {
            "target": target,
            "type": target_type,
            "is_network": target_type in ["ip_range"],
            "is_web": target_type in ["url", "domain"],
            "is_single_host": target_type in ["ip", "domain"],
        }

    def generate_plan(self, target: str) -> Dict[str, Any]:
        """生成测试计划"""
        target_info = self.analyze_target(target)

        phases = []
        for phase in self.STANDARD_PHASES:
            phase_plan = {
                "name": phase.name,
                "description": phase.description,
                "tools": self._select_tools(phase, target_info),
                "objectives": self._customize_objectives(phase, target_info),
                "priority": self._calculate_priority(phase, target_info),
            }
            phases.append(phase_plan)

        plan = {
            "target": target,
            "target_info": target_info,
            "test_phases": phases,
            "estimated_steps": len(phases) * 2,
            "recommended_tools": self._get_recommended_tools(target_info),
        }

        if self.llm_enabled:
            llm_plan = self._enhance_with_llm(target, plan)
            if llm_plan:
                plan = llm_plan

        return plan

    def _select_tools(self, phase: TestPhase, target_info: Dict[str, Any]) -> List[str]:
        """选择适合目标的工具"""
        tools = phase.tools.copy()

        if target_info.get("is_web"):
            if phase.name == "enumeration":
                tools.extend(["gobuster", "nikto", "wpscan"])
            elif phase.name == "vulnerability":
                tools.extend(["sqlmap", "xsser", " nuclei"])

        if target_info.get("is_network"):
            if phase.name == "reconnaissance":
                tools.extend(["masscan", "rustscan"])

        return list(set(tools))

    def _customize_objectives(
        self, phase: TestPhase, target_info: Dict[str, Any]
    ) -> List[str]:
        """自定义目标"""
        objectives = phase.objectives.copy()

        if target_info.get("is_web") and phase.name == "vulnerability":
            objectives.append("测试SQL注入和XSS漏洞")

        if target_info.get("target"):
            objectives = [
                obj.replace("目标", target_info["target"]) for obj in objectives
            ]

        return objectives

    def _calculate_priority(self, phase: TestPhase, target_info: Dict[str, Any]) -> str:
        """计算阶段优先级"""
        if target_info.get("is_web"):
            if phase.name in ["enumeration", "vulnerability"]:
                return "high"

        if target_info.get("is_network"):
            if phase.name in ["reconnaissance", "scanning"]:
                return "high"

        return "medium"

    def _get_recommended_tools(self, target_info: Dict[str, Any]) -> List[str]:
        """获取推荐工具列表"""
        tools = ["nmap"]

        if target_info.get("is_web"):
            tools.extend(["nikto", "gobuster", "sqlmap"])
        else:
            tools.extend(["enum4linux", "hydra"])

        return tools

    def _enhance_with_llm(
        self, target: str, base_plan: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """使用LLM增强计划"""
        try:
            from config.execute_config import LLM_CONFIG
            from langchain_openai import ChatOpenAI

            llm = ChatOpenAI(
                model=LLM_CONFIG["model"],
                base_url=LLM_CONFIG["base_url"],
                api_key=LLM_CONFIG["api_key"],
                temperature=0.5,
            )

            prompt = f"""You are a penetration testing planner. Enhance this test plan for target: {target}

Base Plan: {base_plan}

Provide specific recommendations in JSON format:
{{
  "specific_vulnerabilities_to_check": ["list of specific vulns based on target type"],
  "custom_tools_recommendations": ["additional tools"],
  "risk_assessment": "brief risk assessment",
  "special_considerations": ["any special notes"]
}}"""

            response = llm.invoke(prompt)

            import json
            import re

            content = (
                response.content if hasattr(response, "content") else str(response)
            )
            json_match = re.search(r"\{[^{}]*\}", content, re.DOTALL)

            if json_match:
                llm_insights = json.loads(json_match.group())
                base_plan["llm_insights"] = llm_insights

            return base_plan

        except Exception as e:
            print(f"[Planner] LLM enhancement failed: {e}")
            return None


def generate_test_plan(target: str) -> Dict[str, Any]:
    """生成测试计划的便捷函数"""
    planner = PenetrationTestPlanner()
    return planner.generate_plan(target)


planner = PenetrationTestPlanner()
