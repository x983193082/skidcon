"""
Prompt Loader - Prompt 模板加载器
支持 YAML 文件加载和动态变量替换
"""

import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from functools import lru_cache

from loguru import logger


class PromptLoader:
    """Prompt 模板加载器"""

    def __init__(self, prompts_dir: str = "config/prompts"):
        self.prompts_dir = Path(prompts_dir)

    @lru_cache(maxsize=32)
    def load_agent_prompts(self, agent_type: str) -> Dict[str, Any]:
        """加载指定 Agent 的 prompt 模板"""
        file_path = self.prompts_dir / "agents" / f"{agent_type}.yaml"

        if not file_path.exists():
            logger.warning(f"Prompt file not found: {file_path}")
            return {}

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            logger.debug(f"Loaded prompt for {agent_type}")
            return data
        except Exception as e:
            logger.error(f"Failed to load prompt {agent_type}: {e}")
            return {}

    def get_version(self, agent_type: str) -> str:
        """获取 prompt 版本"""
        prompts = self.load_agent_prompts(agent_type)
        return prompts.get("version", "1.0")

    def get_changelog(self, agent_type: str) -> str:
        """获取 changelog"""
        prompts = self.load_agent_prompts(agent_type)
        return prompts.get("changelog", "")

    def get_role(self, agent_type: str) -> str:
        """获取 role"""
        prompts = self.load_agent_prompts(agent_type)
        agent_key = f"{agent_type}_agent"
        return prompts.get(agent_key, {}).get("role", "")

    def get_goal(self, agent_type: str, **kwargs) -> str:
        """获取 goal（支持动态变量）"""
        prompts = self.load_agent_prompts(agent_type)
        agent_key = f"{agent_type}_agent"
        template = prompts.get(agent_key, {}).get("goal", "")

        if kwargs and template:
            try:
                return template.format(**kwargs)
            except KeyError as e:
                logger.warning(f"Missing variable in goal: {e}, using template as-is")
                return template
        return template

    def get_backstory(self, agent_type: str) -> str:
        """获取 backstory"""
        prompts = self.load_agent_prompts(agent_type)
        agent_key = f"{agent_type}_agent"
        return prompts.get(agent_key, {}).get("backstory", "")

    def get_tasks(self, agent_type: str) -> list:
        """获取任务列表"""
        prompts = self.load_agent_prompts(agent_type)
        agent_key = f"{agent_type}_agent"
        return prompts.get(agent_key, {}).get("tasks", [])

    def get_task(self, agent_type: str, task_name: str) -> Optional[Dict]:
        """获取指定任务"""
        tasks = self.get_tasks(agent_type)
        for task in tasks:
            if task.get("name") == task_name:
                return task
        return None

    def get_all_agents(self) -> list:
        """获取所有可用的 Agent 类型"""
        agents_dir = self.prompts_dir / "agents"
        if not agents_dir.exists():
            return []
        return [f.stem for f in agents_dir.glob("*.yaml")]


_prompt_loader: Optional[PromptLoader] = None


def get_prompt_loader() -> PromptLoader:
    """获取全局 PromptLoader 实例"""
    global _prompt_loader
    if _prompt_loader is None:
        _prompt_loader = PromptLoader()
    return _prompt_loader


def reset_prompt_loader() -> None:
    """重置 PromptLoader（用于测试）"""
    global _prompt_loader
    _prompt_loader = None
