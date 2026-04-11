"""
Prompt Manager - Prompt 管理器
支持运行时更新、动态变量、版本管理
"""

import threading
from typing import Dict, Optional, Any, List
from loguru import logger

from .loader import get_prompt_loader, PromptLoader
from .versions import get_version_manager, VersionManager


class PromptManager:
    """
    Prompt 管理器

    支持：
    - 从文件加载 prompt
    - 运行时更新 prompt
    - 动态变量替换
    - 版本管理
    """

    # 允许运行时更新的 key 白名单
    ALLOWED_KEYS = {"role", "goal", "backstory", "tasks"}

    def __init__(self):
        self._loader = get_prompt_loader()
        self._version_mgr = get_version_manager()
        self._runtime_prompts: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    def get_role(self, agent_type: str) -> str:
        """获取 role"""
        return self._get_prompt(agent_type, "role")

    def get_goal(self, agent_type: str, **kwargs) -> str:
        """获取 goal（支持动态变量）"""
        template = self._get_prompt(agent_type, "goal")
        if kwargs and template:
            try:
                return template.format(**kwargs)
            except KeyError as e:
                logger.warning(f"Missing variable in goal: {e}")
                return template
        return template

    def get_backstory(self, agent_type: str) -> str:
        """获取 backstory"""
        return self._get_prompt(agent_type, "backstory")

    def get_tasks(self, agent_type: str) -> list:
        """获取任务列表"""
        with self._lock:
            runtime_tasks = self._runtime_prompts.get(agent_type, {}).get("tasks")
            if runtime_tasks is not None:
                return runtime_tasks
        return self._loader.get_tasks(agent_type)

    def _get_prompt(self, agent_type: str, key: str) -> str:
        """获取 prompt（优先运行时值，其次文件值）"""
        with self._lock:
            runtime_val = self._runtime_prompts.get(agent_type, {}).get(key)
            if runtime_val is not None:
                return runtime_val

        # 显式映射到 loader 方法
        loader_methods = {
            "role": self._loader.get_role,
            "goal": self._loader.get_goal,
            "backstory": self._loader.get_backstory,
        }
        if key in loader_methods:
            return loader_methods[key](agent_type)
        return ""

    def update_prompt(self, agent_type: str, key: str, value: Any) -> bool:
        """运行时更新 prompt（仅允许白名单 key）"""
        if key not in self.ALLOWED_KEYS:
            logger.error(f"Cannot update key '{key}': not allowed")
            return False

        with self._lock:
            if agent_type not in self._runtime_prompts:
                self._runtime_prompts[agent_type] = {}
            self._runtime_prompts[agent_type][key] = value
            logger.info(f"Updated prompt: {agent_type}.{key}")
            return True

    def reset_prompt(self, agent_type: str, key: str) -> bool:
        """重置 prompt（删除运行时值）"""
        with self._lock:
            if (
                agent_type in self._runtime_prompts
                and key in self._runtime_prompts[agent_type]
            ):
                del self._runtime_prompts[agent_type][key]
                logger.info(f"Reset prompt: {agent_type}.{key}")
                return True
        return False

    def reset_all(self, agent_type: Optional[str] = None) -> bool:
        """重置所有或指定 agent 的 prompt"""
        with self._lock:
            if agent_type:
                self._runtime_prompts.pop(agent_type, None)
            else:
                self._runtime_prompts.clear()
            return True

    def get_current_version(self) -> str:
        """获取当前版本"""
        return self._version_mgr.get_current_version()

    def switch_version(self, version: str) -> bool:
        """切换版本"""
        return self._version_mgr.switch_version(version)

    def get_version_info(self) -> Dict[str, Any]:
        """获取版本信息"""
        versions = self._version_mgr.get_all_versions()
        current = self._version_mgr.get_current_version()
        return {
            "current_version": current,
            "versions": [
                {
                    "version": v.version,
                    "created_at": v.created_at,
                    "changelog": v.changelog,
                    "active": v.active,
                }
                for v in versions
            ],
        }


# 全局实例（线程安全）
_prompt_manager: Optional[PromptManager] = None
_manager_lock = threading.Lock()


def get_prompt_manager() -> PromptManager:
    """获取全局 PromptManager 实例"""
    global _prompt_manager
    if _prompt_manager is None:
        with _manager_lock:
            if _prompt_manager is None:
                _prompt_manager = PromptManager()
    return _prompt_manager


def reset_prompt_manager() -> None:
    """重置 PromptManager（用于测试）"""
    global _prompt_manager
    with _manager_lock:
        _prompt_manager = None
