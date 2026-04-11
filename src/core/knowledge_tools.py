"""
Knowledge Tools - 知识库工具封装
为 CrewAI Agent 提供 CVE 查询和向量知识库搜索能力
"""

import json
import asyncio
import threading
from typing import List, Dict, Any, Optional
from loguru import logger

from crewai.tools import tool

from ..knowledge.cve_fetcher import CVEFetcher
from ..knowledge.vector_store import VectorStore
from ..core.knowledge_interface import KnowledgeEntry
from ..core.settings import get_settings


class KnowledgeTools:
    """知识库工具集合"""

    def __init__(self):
        self._cve_fetcher: Optional[CVEFetcher] = None
        self._vector_store: Optional[VectorStore] = None
        self._initialized = False

    @property
    def cve_fetcher(self) -> CVEFetcher:
        """获取 CVE 查询器（延迟初始化）"""
        if self._cve_fetcher is None:
            self._cve_fetcher = CVEFetcher()
        return self._cve_fetcher

    @property
    def vector_store(self) -> VectorStore:
        """获取向量存储（延迟初始化）"""
        if self._vector_store is None:
            settings = get_settings()
            self._vector_store = VectorStore(
                name="pentest_knowledge",
                backend=settings.vector_db_type or "chroma",
                embedding_model="all-MiniLM-L6-v2",
            )
        return self._vector_store

    async def initialize_vector_store(self) -> None:
        """异步初始化向量存储（应在应用启动时调用）"""
        if not self._initialized and self._vector_store is not None:
            await self._vector_store.initialize()
            self._initialized = True
            logger.info("Vector store initialized")

    async def ensure_initialized(self) -> None:
        """确保向量存储已初始化"""
        if not self._initialized and self._vector_store is not None:
            await self.initialize_vector_store()


# 全局实例（线程安全）
_knowledge_tools: Optional[KnowledgeTools] = None
_knowledge_lock = threading.Lock()


def get_knowledge_tools() -> KnowledgeTools:
    """获取全局知识库工具实例"""
    global _knowledge_tools
    if _knowledge_tools is None:
        with _knowledge_lock:
            if _knowledge_tools is None:
                _knowledge_tools = KnowledgeTools()
    return _knowledge_tools


@tool("search_cve")
def search_cve(product: str, limit: int = 10) -> str:
    """
    搜索 CVE 漏洞信息

    Args:
        product: 产品名称（如 apache, nginx, mysql, redis, ssh）
        limit: 返回结果数量限制，默认 10

    Returns:
        CVE 列表（JSON 格式），包含 CVE ID、描述、CVSS 评分、严重等级

    Example:
        search_cve(product="apache", limit=5)
        -> '[{"cve_id": "CVE-2024-1234", "description": "...", "cvss_score": 9.8, "severity": "CRITICAL"}, ...]'
    """
    try:
        cve_fetcher = get_knowledge_tools().cve_fetcher
        cves = asyncio.run(cve_fetcher.search_by_product(product))

        results = []
        for cve in cves[:limit]:
            results.append(
                {
                    "cve_id": cve.cve_id,
                    "description": cve.description,
                    "cvss_score": cve.cvss_score,
                    "severity": cve.severity,
                    "published_date": cve.published_date,
                    "references": cve.references[:3] if cve.references else [],
                }
            )

        return json.dumps(results, ensure_ascii=False)

    except Exception as e:
        logger.error(f"CVE search failed: {e}")
        return json.dumps({"error": str(e)})


@tool("search_knowledge_base")
def search_knowledge_base(query: str, top_k: int = 5) -> str:
    """
    搜索向量知识库

    Args:
        query: 查询内容（可以是漏洞描述、攻击手法等）
        top_k: 返回结果数量，默认 5

    Returns:
        相似知识条目列表（JSON 格式），包含内容、来源、置信度

    Example:
        search_knowledge_base(query="SQL注入防御绕过", top_k=3)
        -> '[{"content": "...", "source": "nvd", "confidence": 0.95}, ...]'
    """
    try:
        tools = get_knowledge_tools()
        vector_store = tools.vector_store
        asyncio.run(tools.ensure_initialized())

        results = asyncio.run(vector_store.search(query, top_k))

        output = []
        for entry in results:
            output.append(
                {
                    "content": entry.content[:500],
                    "source": entry.source,
                    "confidence": entry.confidence,
                    "metadata": entry.metadata,
                }
            )

        return json.dumps(output, ensure_ascii=False)

    except Exception as e:
        logger.error(f"Knowledge base search failed: {e}")
        return json.dumps({"error": str(e)})


@tool("add_knowledge_entry")
def add_knowledge_entry(
    content: str, entry_type: str = "exploit", metadata: Dict[str, Any] = None
) -> str:
    """
    添加知识库条目

    Args:
        content: 知识内容
        entry_type: 条目类型（exploit/vulnerability/payload）
        metadata: 额外元数据

    Returns:
        执行结果

    Example:
        add_knowledge_entry(content="某 CMS 命令执行 POC", entry_type="exploit", metadata={"cve": "CVE-2024-XXXX"})
    """
    try:
        tools = get_knowledge_tools()
        vector_store = tools.vector_store

        entry = KnowledgeEntry(
            id="",
            content=content,
            metadata=metadata or {"type": entry_type},
            created_at=__import__("datetime").datetime.now(),
            updated_at=__import__("datetime").datetime.now(),
            source="manual",
            confidence=1.0,
        )

        asyncio.run(vector_store.add(entry))

        return json.dumps({"success": True, "message": "Entry added successfully"})

    except Exception as e:
        logger.error(f"Add knowledge entry failed: {e}")
        return json.dumps({"success": False, "error": str(e)})


AVAILABLE_KNOWLEDGE_TOOLS = [search_cve, search_knowledge_base, add_knowledge_entry]
