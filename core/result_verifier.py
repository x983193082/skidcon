"""结果验证器 - 验证工具执行结果的有效性"""

import re
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass


@dataclass
class VerificationResult:
    verified: bool
    confidence: float
    evidence: str
    details: Dict[str, Any]


class ResultVerifier:
    """验证工具执行结果"""

    VERIFICATION_RULES = {
        "information_collection": {
            "success_keywords": [
                "found",
                "discovered",
                "identified",
                "detected",
                "alive",
                "up",
                "reachable",
                "responding",
            ],
            "failure_keywords": [
                "timeout",
                "unreachable",
                "down",
                "offline",
                "no response",
                "failed",
                "error",
            ],
            "data_patterns": [
                r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}",
            ],
        },
        "scanning": {
            "success_keywords": [
                "open",
                "filtered",
                "closed",
                "port",
                "service",
                "version",
                "banner",
            ],
            "failure_keywords": [
                "no ports",
                "no open ports",
                "host seems down",
                "ping failed",
                "unreachable",
            ],
            "data_patterns": [
                r"\d+/tcp\s+open",
                r"port\s+\d+",
            ],
        },
        "enumeration": {
            "success_keywords": [
                "enumerated",
                "found",
                "users",
                "shares",
                "domains",
                "groups",
                "policies",
                "entries",
            ],
            "failure_keywords": [
                "access denied",
                "no entries",
                "empty",
                "permission denied",
                "failed to enumerate",
            ],
            "data_patterns": [
                r"\d+\s+entries?",
                r"user[s]?\s*:",
            ],
        },
        "vulnerability": {
            "success_keywords": [
                "vulnerable",
                "vulnerability",
                "CVE",
                "exploit",
                "risk",
                "issue found",
            ],
            "failure_keywords": [
                "no vulnerabilities",
                "secure",
                "not vulnerable",
                "patched",
                "no issues",
            ],
            "data_patterns": [
                r"CVE-\d{4}-\d{4,}",
            ],
        },
        "web_exploitation": {
            "success_keywords": [
                "injection",
                "xss",
                "sqli",
                "vulnerable",
                "exploited",
                "payload",
                "injected",
            ],
            "failure_keywords": [
                "not vulnerable",
                "no injection",
                "blocked",
                "filtered",
                "waf detected",
            ],
            "data_patterns": [
                r"(?:sql|script|alert|error).*injection",
            ],
        },
        "exploitation": {
            "success_keywords": [
                "shell",
                "access",
                "root",
                "admin",
                "owned",
                "pwned",
                "exploited",
                "reverse shell",
                "meterpreter",
                "session opened",
            ],
            "failure_keywords": [
                "exploit failed",
                "connection failed",
                "no session",
                "payload failed",
                "blocked",
            ],
            "data_patterns": [
                r"session\s+\d+\s+opened",
                r"shell\s+(?:opened|spawned)",
            ],
        },
        "password_crypto": {
            "success_keywords": [
                "cracked",
                "recovered",
                "decoded",
                "decrypted",
                "hash cracked",
                "password found",
            ],
            "failure_keywords": [
                "not cracked",
                "failed to crack",
                "no match",
                "exhausted",
                "no password",
            ],
            "data_patterns": [
                r"[a-f0-9]{32}[:=]",
            ],
        },
        "post_exploitation": {
            "success_keywords": [
                "escalated",
                "root",
                "system",
                "admin",
                "privilege",
                "dumped",
                "extracted",
            ],
            "failure_keywords": [
                "access denied",
                "permission denied",
                "failed to escalate",
                "no privileges",
            ],
            "data_patterns": [
                r"NTLM.*hash",
                r"uid\s*=\s*0",
            ],
        },
        "forensics": {
            "success_keywords": [
                "found",
                "extracted",
                "recovered",
                "analyzed",
                "artifact",
                "evidence",
                "timeline",
            ],
            "failure_keywords": [
                "no artifacts",
                "nothing found",
                "corrupted",
                "unsupported format",
            ],
            "data_patterns": [],
        },
        "reverse_engineering": {
            "success_keywords": [
                "decompiled",
                "disassembled",
                "analyzed",
                "function",
                "binary",
                "code",
            ],
            "failure_keywords": [
                "failed to decompile",
                "unsupported",
                "corrupted",
                "encrypted",
            ],
            "data_patterns": [],
        },
        "wireless_attack": {
            "success_keywords": [
                "captured",
                "handshake",
                "cracked",
                "deauth",
                "key found",
            ],
            "failure_keywords": [
                "no handshake",
                "failed to capture",
                "no clients",
                "timeout",
            ],
            "data_patterns": [
                r"handshake.*captured",
            ],
        },
        "custom_code": {
            "success_keywords": [
                "executed",
                "completed",
                "success",
                "done",
                "finished",
                "output",
            ],
            "failure_keywords": [
                "error",
                "exception",
                "failed",
                "traceback",
                "syntax error",
            ],
            "data_patterns": [],
        },
    }

    def verify(self, category: str, result: str) -> Dict[str, Any]:
        """
        验证结果

        Returns:
            {
                "verified": bool,
                "confidence": float (0-1),
                "evidence": str,
                "details": dict
            }
        """
        if not result:
            return {
                "verified": False,
                "confidence": 0.0,
                "evidence": "No result",
                "details": {"reason": "empty_result"},
            }

        rules = self.VERIFICATION_RULES.get(
            category, self.VERIFICATION_RULES["custom_code"]
        )

        keyword_score = self._check_keywords(result, rules)
        pattern_score = self._check_patterns(result, rules)

        final_score = keyword_score * 0.6 + pattern_score * 0.4
        verified = final_score >= 0.5

        evidence = self._extract_evidence(result, rules)

        return {
            "verified": verified,
            "confidence": round(final_score, 2),
            "evidence": evidence,
            "details": {
                "keyword_score": keyword_score,
                "pattern_score": pattern_score,
                "category": category,
            },
        }

    def _check_keywords(self, result: str, rules: Dict[str, Any]) -> float:
        """检查关键词"""
        result_lower = result.lower()

        success_count = sum(
            1 for kw in rules.get("success_keywords", []) if kw.lower() in result_lower
        )
        failure_count = sum(
            1 for kw in rules.get("failure_keywords", []) if kw.lower() in result_lower
        )

        if success_count == 0 and failure_count == 0:
            return 0.5

        total = success_count + failure_count
        return success_count / total if total > 0 else 0.5

    def _check_patterns(self, result: str, rules: Dict[str, Any]) -> float:
        """检查数据模式"""
        patterns = rules.get("data_patterns", [])
        if not patterns:
            return 0.5

        matches = 0
        for pattern in patterns:
            if re.search(pattern, result, re.IGNORECASE):
                matches += 1

        return min(1.0, matches / max(1, len(patterns)) + 0.5)

    def _extract_evidence(self, result: str, rules: Dict[str, Any]) -> str:
        """提取证据片段"""
        evidence_parts = []

        for pattern in rules.get("data_patterns", []):
            match = re.search(pattern, result, re.IGNORECASE)
            if match:
                start = max(0, match.start() - 30)
                end = min(len(result), match.end() + 30)
                evidence_parts.append(result[start:end].strip())

        for kw in rules.get("success_keywords", [])[:3]:
            if kw.lower() in result.lower():
                idx = result.lower().find(kw.lower())
                start = max(0, idx - 20)
                end = min(len(result), idx + len(kw) + 50)
                snippet = result[start:end].strip()
                if snippet not in evidence_parts:
                    evidence_parts.append(snippet)
                break

        if evidence_parts:
            return " | ".join(evidence_parts[:2])

        return result[:200] if len(result) > 200 else result

    def verify_with_llm(
        self, category: str, result: str, llm_client=None
    ) -> Dict[str, Any]:
        """使用LLM进行高级验证（可选）"""
        basic_result = self.verify(category, result)

        if basic_result["confidence"] >= 0.8:
            return basic_result

        if llm_client is None:
            return basic_result

        try:
            prompt = f"""Analyze this security tool output and determine if the execution was successful.

Category: {category}
Output:
{result[:1000]}

Respond with JSON:
{{"verified": true/false, "confidence": 0.0-1.0, "summary": "brief summary"}}"""

            response = llm_client.invoke(prompt)
            llm_result = self._parse_llm_response(
                response.content if hasattr(response, "content") else str(response)
            )

            return {
                "verified": llm_result.get("verified", basic_result["verified"]),
                "confidence": max(
                    basic_result["confidence"], llm_result.get("confidence", 0)
                ),
                "evidence": basic_result["evidence"],
                "details": {**basic_result["details"], "llm_verified": True},
            }
        except Exception:
            return basic_result

    def _parse_llm_response(self, response: str) -> Dict[str, Any]:
        """解析LLM响应"""
        import json

        try:
            json_match = re.search(r"\{[^}]+\}", response)
            if json_match:
                return json.loads(json_match.group())
        except (json.JSONDecodeError, AttributeError):
            pass
        return {"verified": False, "confidence": 0.5}
