"""
Prompt Version Manager - Prompt 版本管理
支持版本切换、历史记录
"""

import json
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
from loguru import logger


@dataclass
class PromptVersion:
    version: str
    created_at: str
    changelog: str
    active: bool = False


class VersionManager:
    """Prompt 版本管理器 - 全局版本控制"""

    def __init__(self, prompts_dir: str = "config/prompts"):
        self.prompts_dir = Path(prompts_dir)
        self._version_file = self.prompts_dir / "versions.json"
        self._current_version: Optional[str] = None
        self._versions: Dict[str, PromptVersion] = {}
        self._load_versions()

    def _load_versions(self) -> None:
        """加载版本信息"""
        if not self._version_file.exists():
            self._init_versions()
            return

        try:
            with open(self._version_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._current_version = data.get("current_version", "1.0")
                for v in data.get("versions", []):
                    self._versions[v["version"]] = PromptVersion(**v)
            logger.info(f"Loaded {len(self._versions)} prompt versions")
        except Exception as e:
            logger.error(f"Failed to load versions: {e}")
            self._init_versions()

    def _init_versions(self) -> None:
        """初始化版本"""
        self._current_version = "1.0"
        self._versions = {
            "1.0": PromptVersion(
                version="1.0",
                created_at=datetime.now().isoformat(),
                changelog="初始版本",
                active=True,
            )
        }
        self._save_versions()

    def _save_versions(self) -> None:
        """保存版本信息"""
        try:
            self._version_file.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "current_version": self._current_version,
                "versions": [asdict(v) for v in self._versions.values()],
            }
            with open(self._version_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save versions: {e}")

    def get_current_version(self) -> str:
        """获取当前活跃版本"""
        return self._current_version

    def get_all_versions(self) -> List[PromptVersion]:
        """获取所有版本"""
        return list(self._versions.values())

    def switch_version(self, version: str) -> bool:
        """切换版本"""
        if version not in self._versions:
            logger.error(f"Version {version} not found")
            return False

        self._current_version = version

        for v in self._versions.values():
            v.active = v.version == version

        self._save_versions()
        logger.info(f"Switched to prompt version: {version}")
        return True

    def create_version(
        self, version: str, changelog: str, copy_from: str = None
    ) -> bool:
        """创建新版本"""
        if version in self._versions:
            logger.warning(f"Version {version} already exists")
            return False

        new_version = PromptVersion(
            version=version,
            created_at=datetime.now().isoformat(),
            changelog=changelog,
            active=False,
        )

        self._versions[version] = new_version
        self._save_versions()
        logger.info(f"Created new prompt version: {version}")
        return True

    def get_version_info(self, version: str) -> Optional[PromptVersion]:
        """获取指定版本信息"""
        return self._versions.get(version)

    def delete_version(self, version: str) -> bool:
        """删除版本（不能删除当前活跃版本）"""
        if version == self._current_version:
            logger.error("Cannot delete active version")
            return False

        if version in self._versions:
            del self._versions[version]
            self._save_versions()
            logger.info(f"Deleted prompt version: {version}")
            return True
        return False


_version_manager: Optional[VersionManager] = None


def get_version_manager() -> VersionManager:
    """获取全局 VersionManager 实例"""
    global _version_manager
    if _version_manager is None:
        _version_manager = VersionManager()
    return _version_manager


def reset_version_manager() -> None:
    """重置 VersionManager（用于测试）"""
    global _version_manager
    _version_manager = None
