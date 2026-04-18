"""决策引擎 - 决定下一步测试行动"""

import re
import json
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from core.test_state import TestState


@dataclass
class Decision:
    action: str
    category: str
    next_phase: str
    reasoning: str
    source: str
    is_complete: bool = False


class DecisionEngine:
    """渗透测试决策引擎"""

    PHASE_ORDER = [
        "reconnaissance",
        "scanning",
        "enumeration",
        "vulnerability",
        "exploitation",
        "post_exploitation",
        "reporting",
    ]

    PHASE_ACTIONS = {
        "reconnaissance": [
            {
                "condition": lambda s: len(s.discovered_hosts) == 0,
                "action": "使用nmap扫描目标网段发现存活主机",
                "category": "information_collection",
            },
            {
                "condition": lambda s: len(s.discovered_hosts) > 0,
                "action": "对发现的主机进行DNS反向解析",
                "category": "information_collection",
            },
        ],
        "scanning": [
            {
                "condition": lambda s: len(s.discovered_services) == 0,
                "action": "使用nmap进行端口扫描，识别开放端口和服务版本",
                "category": "scanning",
            },
            {
                "condition": lambda s: len(s.discovered_services) > 0,
                "action": "对发现的开放端口进行服务版本探测",
                "category": "scanning",
            },
        ],
        "enumeration": [
            {
                "condition": lambda s: any(
                    svc.service.lower() in ["ssh", "sshd"]
                    for svc in s.discovered_services
                ),
                "action": "枚举SSH服务，检查是否允许root登录和弱密码",
                "category": "enumeration",
            },
            {
                "condition": lambda s: any(
                    svc.service.lower() in ["http", "https", "http-alt"]
                    for svc in s.discovered_services
                ),
                "action": "使用目录扫描工具枚举Web目录和文件",
                "category": "enumeration",
            },
            {
                "condition": lambda s: any(
                    svc.service.lower() in ["smb", "microsoft-ds", "netbios-ssn"]
                    for svc in s.discovered_services
                ),
                "action": "使用enum4linux枚举SMB共享和用户信息",
                "category": "enumeration",
            },
            {
                "condition": lambda s: any(
                    svc.service.lower() in ["ftp"] for svc in s.discovered_services
                ),
                "action": "检查FTP匿名登录和枚举可写目录",
                "category": "enumeration",
            },
            {
                "condition": lambda s: any(
                    svc.service.lower() in ["mysql", "mysql3306"]
                    for svc in s.discovered_services
                ),
                "action": "尝试MySQL匿名登录并枚举数据库",
                "category": "enumeration",
            },
            {
                "condition": lambda s: len(s.discovered_services) > 0,
                "action": "对所有发现的服务进行详细枚举",
                "category": "enumeration",
            },
        ],
        "vulnerability": [
            {
                "condition": lambda s: any(
                    svc.service.lower() in ["http", "https"]
                    for svc in s.discovered_services
                ),
                "action": "对Web应用进行SQL注入和XSS漏洞扫描",
                "category": "web_exploitation",
            },
            {
                "condition": lambda s: len(s.discovered_services) > 0,
                "action": "使用漏洞扫描器检查已知CVE漏洞",
                "category": "vulnerability",
            },
        ],
        "exploitation": [
            {
                "condition": lambda s: len(s.discovered_vulns) > 0,
                "action": "尝试利用发现的漏洞获取初始访问权限",
                "category": "exploitation",
            },
            {
                "condition": lambda s: len(s.discovered_creds) > 0,
                "action": "使用获取的凭据尝试登录服务",
                "category": "exploitation",
            },
        ],
        "post_exploitation": [
            {
                "condition": lambda s: len(s.discovered_creds) > 0,
                "action": "进行权限提升，尝试获取root或system权限",
                "category": "post_exploitation",
            },
            {
                "condition": lambda s: True,
                "action": "收集系统信息和敏感文件",
                "category": "post_exploitation",
            },
        ],
        "reporting": [
            {
                "condition": lambda s: True,
                "action": "生成渗透测试报告",
                "category": "custom_code",
                "complete": True,
            },
        ],
    }

    def __init__(self):
        self.step_count = 0
        self.llm_fallback_enabled = True

    def decide_next(
        self, state: TestState, last_result: str = "", last_verified: bool = False
    ) -> Dict[str, Any]:
        """
        决定下一步行动

        Returns:
            {
                "action": str,           # 要执行的查询
                "category": str,         # 任务类别
                "next_phase": str,       # 下一个阶段
                "reasoning": str,        # 决策理由
                "source": str,           # "rule" 或 "llm"
                "is_complete": bool      # 测试是否完成
            }
        """
        self.step_count += 1

        decision = self._rule_based_decision(state, last_result, last_verified)

        if decision is None:
            decision = self._llm_decision(state, last_result)

        if decision is None:
            decision = self._default_decision(state)

        return decision

    def _rule_based_decision(
        self, state: TestState, last_result: str, last_verified: bool
    ) -> Optional[Dict[str, Any]]:
        """基于规则的决策"""

        current_phase = state.phase
        phase_idx = (
            self.PHASE_ORDER.index(current_phase)
            if current_phase in self.PHASE_ORDER
            else 0
        )

        actions = self.PHASE_ACTIONS.get(current_phase, [])

        for action_def in actions:
            try:
                if action_def["condition"](state):
                    next_phase = current_phase

                    if last_verified and self._should_advance(state, current_phase):
                        next_idx = min(phase_idx + 1, len(self.PHASE_ORDER) - 1)
                        next_phase = self.PHASE_ORDER[next_idx]

                    return {
                        "action": self._customize_action(action_def["action"], state),
                        "category": action_def["category"],
                        "next_phase": next_phase,
                        "reasoning": f"Phase {current_phase}: condition matched for {action_def['category']}",
                        "source": "rule",
                        "is_complete": action_def.get("complete", False),
                    }
            except Exception:
                continue

        if self._phase_complete(state, current_phase):
            next_idx = min(phase_idx + 1, len(self.PHASE_ORDER) - 1)
            next_phase = self.PHASE_ORDER[next_idx]

            if next_phase == "reporting":
                return {
                    "action": "生成渗透测试报告",
                    "category": "custom_code",
                    "next_phase": "reporting",
                    "reasoning": "All phases completed, generating report",
                    "source": "rule",
                    "is_complete": True,
                }

            next_actions = self.PHASE_ACTIONS.get(next_phase, [])
            if next_actions:
                return {
                    "action": self._customize_action(next_actions[0]["action"], state),
                    "category": next_actions[0]["category"],
                    "next_phase": next_phase,
                    "reasoning": f"Advancing to {next_phase} phase",
                    "source": "rule",
                    "is_complete": False,
                }

        return None

    def _should_advance(self, state: TestState, current_phase: str) -> bool:
        """判断是否应该进入下一阶段"""
        advance_criteria = {
            "reconnaissance": len(state.discovered_hosts) > 0,
            "scanning": len(state.discovered_services) > 0,
            "enumeration": len(state.executed_steps) >= 2
            and state.phase == "enumeration",
            "vulnerability": len(state.discovered_vulns) > 0
            or len(state.executed_steps) >= 2,
            "exploitation": len(state.discovered_creds) > 0
            or len(state.executed_steps) >= 2,
            "post_exploitation": len(state.executed_steps) >= 1,
        }
        return advance_criteria.get(current_phase, False)

    def _phase_complete(self, state: TestState, phase: str) -> bool:
        """判断阶段是否完成"""
        min_steps_per_phase = 2
        phase_steps = [s for s in state.executed_steps if s.phase == phase]
        return len(phase_steps) >= min_steps_per_phase

    def _customize_action(self, action_template: str, state: TestState) -> str:
        """自定义行动描述，填入具体目标信息"""
        action = action_template

        if "{target}" in action:
            action = action.replace("{target}", state.target)

        if state.discovered_hosts:
            hosts_str = ", ".join(state.discovered_hosts[:3])
            action = action.replace("目标网段", f"{hosts_str}等主机")

        if state.discovered_services:
            ports = [f"{s.port}/{s.service}" for s in state.discovered_services[:5]]
            action += f" (已发现端口: {', '.join(ports)})"

        return action

    def _llm_decision(
        self, state: TestState, last_result: str
    ) -> Optional[Dict[str, Any]]:
        """使用LLM进行决策（当规则不适用时）"""
        if not self.llm_fallback_enabled:
            return None

        try:
            from config.execute_config import LLM_CONFIG
            from langchain_openai import ChatOpenAI

            llm = ChatOpenAI(
                model=LLM_CONFIG["model"],
                base_url=LLM_CONFIG["base_url"],
                api_key=LLM_CONFIG["api_key"],
                temperature=0.3,
            )

            prompt = self._build_llm_prompt(state, last_result)

            response = llm.invoke(prompt)

            return self._parse_llm_decision(
                response.content if hasattr(response, "content") else str(response),
                state,
            )

        except Exception as e:
            print(f"[DecisionEngine] LLM decision failed: {e}")
            return None

    def _build_llm_prompt(self, state: TestState, last_result: str) -> str:
        """构建LLM决策提示"""
        return f"""You are a penetration testing decision engine. Based on the current test state, decide the next action.

Current State:
- Target: {state.target}
- Current Phase: {state.phase}
- Discovered Hosts: {len(state.discovered_hosts)}
- Discovered Services: {len(state.discovered_services)}
- Found Vulnerabilities: {len(state.discovered_vulns)}
- Found Credentials: {len(state.discovered_creds)}
- Steps Completed: {len(state.executed_steps)}

Last Result Summary: {last_result[:300] if last_result else "None"}

Available Phases: reconnaissance -> scanning -> enumeration -> vulnerability -> exploitation -> post_exploitation -> reporting

Respond with JSON only:
{{
  "action": "具体要执行的操作，用中文描述",
  "category": "任务类别(information_collection/scanning/enumeration/web_exploitation/exploitation/password_crypto/post_exploitation/custom_code)",
  "next_phase": "下一阶段名称",
  "reasoning": "决策理由",
  "is_complete": false
}}"""

    def _parse_llm_decision(
        self, response: str, state: TestState
    ) -> Optional[Dict[str, Any]]:
        """解析LLM决策响应"""
        try:
            json_match = re.search(r"\{[^{}]*\}", response, re.DOTALL)
            if json_match:
                decision = json.loads(json_match.group())

                if decision.get("action"):
                    return {
                        "action": decision["action"],
                        "category": decision.get("category", "scanning"),
                        "next_phase": decision.get("next_phase", state.phase),
                        "reasoning": decision.get("reasoning", "LLM decision"),
                        "source": "llm",
                        "is_complete": decision.get("is_complete", False),
                    }
        except (json.JSONDecodeError, AttributeError):
            pass

        return None

    def _default_decision(self, state: TestState) -> Dict[str, Any]:
        """默认决策"""
        phase_idx = (
            self.PHASE_ORDER.index(state.phase)
            if state.phase in self.PHASE_ORDER
            else 0
        )

        if len(state.executed_steps) >= 10:
            return {
                "action": "生成渗透测试报告",
                "category": "custom_code",
                "next_phase": "reporting",
                "reasoning": "Maximum steps reached, generating report",
                "source": "default",
                "is_complete": True,
            }

        next_idx = min(phase_idx + 1, len(self.PHASE_ORDER) - 1)
        next_phase = self.PHASE_ORDER[next_idx]

        return {
            "action": f"对目标{state.target}执行{next_phase}阶段测试",
            "category": "scanning",
            "next_phase": next_phase,
            "reasoning": "Default progression to next phase",
            "source": "default",
            "is_complete": False,
        }
