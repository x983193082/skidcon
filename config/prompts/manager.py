"""
Prompt Manager - Prompt 管理器
支持运行时更新、动态变量、版本管理
"""

from typing import Dict, Optional, Any
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

    def __init__(self):
        self._loader = get_prompt_loader()
        self._version_mgr = get_version_manager()
        self._runtime_prompts: Dict[str, Dict[str, str]] = {}

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
        runtime_key = f"{agent_type}_tasks"
        if (
            agent_type in self._runtime_prompts
            and runtime_key in self._runtime_prompts[agent_type]
        ):
            return self._runtime_prompts[agent_type][runtime_key]

        return self._loader.get_tasks(agent_type)

    def _get_prompt(self, agent_type: str, key: str) -> str:
        """获取 prompt（优先运行时值，其次文件值）"""
        if (
            agent_type in self._runtime_prompts
            and key in self._runtime_prompts[agent_type]
        ):
            return self._runtime_prompts[agent_type][key]

        loader_method = f"get_{key}"
        if hasattr(self._loader, loader_method):
            return getattr(self._loader, loader_method)(agent_type)

        return ""

    def update_prompt(self, agent_type: str, key: str, value: str) -> bool:
        """运行时更新 prompt"""
        if agent_type not in self._runtime_prompts:
            self._runtime_prompts[agent_type] = {}

        self._runtime_prompts[agent_type][key] = value
        logger.info(f"Updated prompt: {agent_type}.{key}")
        return True

    def reset_prompt(self, agent_type: str, key: str) -> bool:
        """重置 prompt（删除运行时值）"""
        if (
            agent_type in self._runtime_prompts
            and key in self._runtime_prompts[agent_type]
        ):
            del self._runtime_prompts[agent_type][key]
            logger.info(f"Reset prompt: {agent_type}.{key}")
            return True
        return False

    def reset_all(self, agent_type: str = None) -> bool:
        """重置所有或指定 agent 的 prompt"""
        if agent_type:
            if agent_type in self._runtime_prompts:
                self._runtime_prompts[agent_type].clear()
            return True
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


_prompt_manager: Optional[PromptManager] = None


def get_prompt_manager() -> PromptManager:
    """获取全局 PromptManager 实例"""
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptManager()
    return _prompt_manager


def reset_prompt_manager() -> None:
    """重置 PromptManager（用于测试）"""
    global _prompt_manager
    _prompt_manager = None
