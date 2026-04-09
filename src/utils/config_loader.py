"""
Config Loader - 配置加载器
加载 YAML 配置文件
"""
import os
from pathlib import Path
from typing import Any, Dict, Optional
import yaml
from loguru import logger


class ConfigLoader:
    """配置加载器"""

    def __init__(self, config_dir: str = "config"):
        self.config_dir = Path(config_dir)
        self._configs: Dict[str, Any] = {}

    def load_all(self) -> Dict[str, Any]:
        """加载所有配置文件"""
        configs = {}

        # 加载 agents.yaml
        configs["agents"] = self.load_config("agents.yaml")

        # 加载 tools.yaml
        configs["tools"] = self.load_config("tools.yaml")

        # 加载 attack_patterns.yaml
        configs["attack_patterns"] = self.load_config("attack_patterns.yaml")

        self._configs = configs
        logger.info(f"Loaded {len(configs)} config files")

        return configs

    def load_config(self, filename: str) -> Optional[Dict]:
        """
        加载单个配置文件

        Args:
            filename: 配置文件名

        Returns:
            配置字典
        """
        config_path = self.config_dir / filename

        if not config_path.exists():
            logger.warning(f"Config file not found: {config_path}")
            return None

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
                logger.debug(f"Loaded config: {filename}")
                return config
        except Exception as e:
            logger.error(f"Failed to load config {filename}: {e}")
            return None

    def get_agent_config(self, agent_name: str) -> Optional[Dict]:
        """获取指定 Agent 的配置"""
        if not self._configs:
            self.load_all()

        agents = self._configs.get("agents", {}).get("agents", {})
        return agents.get(agent_name)

    def get_tool_config(self, tool_name: str) -> Optional[Dict]:
        """获取指定工具的配置"""
        if not self._configs:
            self.load_all()

        tools = self._configs.get("tools", {}).get("tools", {})
        return tools.get(tool_name)

    def get_attack_pattern(self, pattern_name: str) -> Optional[Dict]:
        """获取攻击模式配置"""
        if not self._configs:
            self.load_all()

        patterns = self._configs.get("attack_patterns", {}).get("attack_patterns", {})
        return patterns.get(pattern_name)

    def validate_config(self, config: Dict, required_keys: list) -> bool:
        """
        验证配置是否包含必需字段

        Args:
            config: 配置字典
            required_keys: 必需字段列表

        Returns:
            是否有效
        """
        for key in required_keys:
            if key not in config:
                logger.error(f"Missing required key: {key}")
                return False
        return True


# 全局配置加载器实例
_config_loader: Optional[ConfigLoader] = None


def get_config_loader() -> ConfigLoader:
    """获取全局配置加载器实例"""
    global _config_loader
    if _config_loader is None:
        config_dir = os.getenv("CONFIG_DIR", "config")
        _config_loader = ConfigLoader(config_dir)
    return _config_loader