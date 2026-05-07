"""SkidCon 日志系统 - 命令执行日志、对话历史持久化、渗透测试日志"""

import json
import os
import threading
from datetime import datetime
from typing import Optional, Dict, Any


class SkidConLogger:
    """统一日志管理器，提供命令执行日志、对话历史持久化、渗透测试日志"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, log_dir: str = None):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    cls._instance = instance
        return cls._instance

    def __init__(self, log_dir: str = None):
        if self._initialized:
            return
        self.log_dir = log_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs"
        )
        os.makedirs(self.log_dir, exist_ok=True)
        self._file_lock = threading.Lock()
        self._initialized = True

    def _get_timestamp(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _get_date_str(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def _write_jsonl(self, filepath: str, data: dict):
        with self._file_lock:
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")

    def _write_json(self, filepath: str, data: dict):
        with self._file_lock:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    # ==================== 命令执行日志 ====================

    def log_command(
        self,
        command: str,
        output: str,
        duration: float = 0,
        exit_code: int = 0,
        tool_type: str = "shell",
    ) -> None:
        """
        记录命令执行日志

        Args:
            command: 执行的命令
            output: 命令输出
            duration: 执行时长（秒）
            exit_code: 退出码
            tool_type: 工具类型（shell/python）
        """
        log_entry = {
            "timestamp": self._get_timestamp(),
            "tool_type": tool_type,
            "command": command[:500],
            "exit_code": exit_code,
            "duration_seconds": round(duration, 2),
            "output_length": len(output) if output else 0,
            "output_preview": (output[:1000] if output else ""),
            "success": exit_code == 0,
        }

        filepath = os.path.join(self.log_dir, f"commands_{self._get_date_str()}.jsonl")
        self._write_jsonl(filepath, log_entry)

    # ==================== 对话历史持久化 ====================

    def save_conversation(
        self,
        user_query: str,
        ai_response: Optional[str],
        agent_type: str = "unknown",
        task_id: Optional[str] = None,
    ) -> None:
        """
        保存对话到持久化文件

        Args:
            user_query: 用户查询
            ai_response: AI响应
            agent_type: Agent类型
            task_id: 任务ID
        """
        log_entry = {
            "timestamp": self._get_timestamp(),
            "task_id": task_id,
            "agent_type": agent_type,
            "user_query": user_query[:500],
            "ai_response_preview": (ai_response[:1000] if ai_response else None),
            "ai_response_length": len(ai_response) if ai_response else 0,
        }

        filepath = os.path.join(
            self.log_dir, f"conversations_{self._get_date_str()}.jsonl"
        )
        self._write_jsonl(filepath, log_entry)

    def load_conversations(self, date_str: str = None) -> list:
        """
        从持久化文件加载对话历史

        Args:
            date_str: 日期字符串，格式 YYYY-MM-DD，默认今天

        Returns:
            对话条目列表
        """
        date_str = date_str or self._get_date_str()
        filepath = os.path.join(self.log_dir, f"conversations_{date_str}.jsonl")

        if not os.path.exists(filepath):
            return []

        conversations = []
        with self._file_lock:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            conversations.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        return conversations

    # ==================== 渗透测试日志 ====================

    def log_pentest_event(
        self,
        target: str,
        phase: str,
        action: str,
        result: str = "",
        findings: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        记录渗透测试事件

        Args:
            target: 目标地址
            phase: 测试阶段（reconnaissance/scanning/enumeration/exploitation等）
            action: 执行的动作
            result: 执行结果摘要
            findings: 发现的信息（如开放端口、漏洞等）
        """
        log_entry = {
            "timestamp": self._get_timestamp(),
            "target": target,
            "phase": phase,
            "action": action[:500],
            "result_preview": (result[:500] if result else ""),
            "findings": findings or {},
        }

        # 写入每日日志
        filepath = os.path.join(self.log_dir, f"pentest_{self._get_date_str()}.jsonl")
        self._write_jsonl(filepath, log_entry)

        # 更新当前目标的渗透测试摘要
        self._update_pentest_summary(target, phase, action, result, findings)

    def _update_pentest_summary(
        self,
        target: str,
        phase: str,
        action: str,
        result: str,
        findings: Optional[Dict[str, Any]],
    ) -> None:
        """更新当前目标的渗透测试摘要文件"""
        summary_path = os.path.join(
            self.log_dir,
            f"pentest_summary_{target.replace('.', '_').replace('/', '_')}.json",
        )

        summary = {}
        if os.path.exists(summary_path):
            try:
                with open(summary_path, "r", encoding="utf-8") as f:
                    summary = json.load(f)
            except (json.JSONDecodeError, IOError):
                summary = {}

        # 更新摘要
        if "target" not in summary:
            summary["target"] = target
            summary["start_time"] = self._get_timestamp()
            summary["phases"] = {}
            summary["all_findings"] = {}

        summary["last_update"] = self._get_timestamp()
        summary["last_phase"] = phase

        # 更新阶段信息
        if phase not in summary["phases"]:
            summary["phases"][phase] = {"actions": [], "count": 0}
        summary["phases"][phase]["count"] = summary["phases"][phase].get("count", 0) + 1
        summary["phases"][phase]["actions"].append(
            {
                "action": action[:200],
                "timestamp": self._get_timestamp(),
                "result": (result[:200] if result else ""),
            }
        )

        # 只保留最近10个action
        summary["phases"][phase]["actions"] = summary["phases"][phase]["actions"][-10:]

        # 更新发现
        if findings:
            for key, value in findings.items():
                if isinstance(value, list):
                    existing = summary["all_findings"].get(key, [])
                    existing_set = set(str(x) for x in existing)
                    for item in value:
                        if str(item) not in existing_set:
                            existing.append(item)
                    summary["all_findings"][key] = existing
                else:
                    summary["all_findings"][key] = value

        self._write_json(summary_path, summary)

    def get_pentest_summary(self, target: str) -> Dict[str, Any]:
        """
        获取目标的渗透测试摘要

        Args:
            target: 目标地址

        Returns:
            渗透测试摘要字典
        """
        summary_path = os.path.join(
            self.log_dir,
            f"pentest_summary_{target.replace('.', '_').replace('/', '_')}.json",
        )

        if not os.path.exists(summary_path):
            return {"target": target, "phases": {}, "all_findings": {}}

        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {"target": target, "phases": {}, "all_findings": {}}

    # ==================== 错误日志 ====================

    def log_error(
        self, error_type: str, error_msg: str, context: Optional[Dict] = None
    ) -> None:
        """
        记录错误日志

        Args:
            error_type: 错误类型（如 streaming_error, command_timeout等）
            error_msg: 错误消息
            context: 额外上下文信息
        """
        log_entry = {
            "timestamp": self._get_timestamp(),
            "error_type": error_type,
            "error_msg": error_msg[:500],
            "context": context or {},
        }

        filepath = os.path.join(self.log_dir, f"errors_{self._get_date_str()}.jsonl")
        self._write_jsonl(filepath, log_entry)


logger = SkidConLogger()
