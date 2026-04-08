"""
Knowledge Interface - 知识库抽象基类
用于漏洞库、CVE、攻击链记忆等知识管理
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class KnowledgeEntry:
    """知识条目标准格式"""
    id: str
    content: str
    metadata: Dict[str, Any]
    created_at: datetime
    updated_at: datetime
    source: str = "unknown"
    confidence: float = 1.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "source": self.source,
            "confidence": self.confidence
        }


class BaseKnowledge(ABC):
    """
    知识库抽象基类
    
    支持向量数据库和图数据库的统一接口
    """
    
    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
    
    @abstractmethod
    async def add(self, entry: KnowledgeEntry) -> bool:
        """
        添加知识条目
        
        Args:
            entry: 知识条目
        
        Returns:
            是否添加成功
        """
        pass
    
    @abstractmethod
    async def search(self, query: str, top_k: int = 5) -> List[KnowledgeEntry]:
        """
        语义搜索知识
        
        Args:
            query: 查询文本
            top_k: 返回数量
        
        Returns:
            匹配的知识条目列表
        """
        pass
    
    @abstractmethod
    async def get(self, entry_id: str) -> Optional[KnowledgeEntry]:
        """
        根据ID获取知识条目
        
        Args:
            entry_id: 条目ID
        
        Returns:
            知识条目或None
        """
        pass
    
    @abstractmethod
    async def update(self, entry_id: str, updates: Dict[str, Any]) -> bool:
        """
        更新知识条目
        
        Args:
            entry_id: 条目ID
            updates: 更新内容
        
        Returns:
            是否更新成功
        """
        pass
    
    @abstractmethod
    async def delete(self, entry_id: str) -> bool:
        """
        删除知识条目
        
        Args:
            entry_id: 条目ID
        
        Returns:
            是否删除成功
        """
        pass
    
    @abstractmethod
    async def clear(self) -> bool:
        """
        清空知识库
        
        Returns:
            是否清空成功
        """
        pass
    
    @abstractmethod
    async def count(self) -> int:
        """
        获取知识条目总数
        
        Returns:
            条目数量
        """
        pass
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name='{self.name}'>"
