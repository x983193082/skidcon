"""
Database - SQLite 数据库连接和会话管理
针对 SQLite 优化
"""

from typing import Generator, Optional
from contextlib import contextmanager
from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool
from loguru import logger

from ..core.settings import get_settings


class Database:
    """SQLite 数据库连接管理器（单例模式）"""

    _instance: Optional["Database"] = None

    def __init__(self) -> None:
        settings = get_settings()
        self.database_url = settings.database_url

        # SQLite 配置
        connect_args = {"check_same_thread": False}
        # 对于文件数据库，使用 NullPool 让每个线程获取独立连接，避免写冲突
        pool_class = NullPool

        self.engine = create_engine(
            self.database_url,
            connect_args=connect_args,
            poolclass=pool_class,
            echo=settings.database_echo,
            # pool_pre_ping 不适用于 SQLite，移除
        )

        self.SessionLocal = sessionmaker(
            bind=self.engine, autocommit=False, autoflush=False
        )

        # 脱敏日志：仅打印文件名
        db_file = self._extract_db_file(self.database_url)
        logger.info(f"Database initialized: {db_file}")

    @staticmethod
    def _extract_db_file(url: str) -> str:
        """从 SQLite URL 中提取文件路径"""
        parsed = urlparse(url)
        return parsed.path or ":memory:"

    @classmethod
    def get_instance(cls) -> "Database":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        if cls._instance and hasattr(cls._instance, "engine"):
            cls._instance.engine.dispose()
        cls._instance = None

    def create_tables(self) -> None:
        """创建所有表"""
        from .db_models import Base

        Base.metadata.create_all(bind=self.engine)
        logger.info("Database tables created")

    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """获取同步数据库会话"""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def get_database() -> Database:
    """获取数据库单例"""
    return Database.get_instance()
