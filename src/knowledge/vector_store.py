"""
Vector Store - 向量数据库封装
支持 Chroma / Qdrant
"""
import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime
import uuid
from loguru import logger

from ..core.knowledge_interface import BaseKnowledge, KnowledgeEntry


class VectorStore(BaseKnowledge):
    """
    向量数据库封装类

    支持多种后端：Chroma, Qdrant
    默认使用 Chroma（轻量，无需额外服务）
    """

    def __init__(
        self,
        name: str = "default",
        backend: str = "chroma",
        embedding_model: str = "all-MiniLM-L6-v2",
        persist_directory: Optional[str] = None
    ):
        super().__init__(name, description="Vector database for knowledge storage")
        self.backend = backend
        self.embedding_model_name = embedding_model
        self.persist_directory = persist_directory or f"./data/vector_{backend}"
        self._client = None
        self._collection = None
        self._embedding_model = None
        self._lock = asyncio.Lock()

    async def _get_embedding(self, text: str) -> Optional[List[float]]:
        """
        获取文本的向量嵌入，失败返回 None
        """
        if self._embedding_model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._embedding_model = SentenceTransformer(self.embedding_model_name)
            except ImportError:
                logger.error("sentence-transformers not installed. Embedding unavailable.")
                return None

        try:
            loop = asyncio.get_event_loop()
            embedding = await loop.run_in_executor(
                None, self._embedding_model.encode, text
            )
            return embedding.tolist()
        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            return None

    async def initialize(self) -> bool:
        """初始化向量数据库连接"""
        try:
            if self.backend == "chroma":
                import chromadb
                from chromadb.config import Settings

                self._client = chromadb.PersistentClient(
                    path=self.persist_directory,
                    settings=Settings(anonymized_telemetry=False)
                )
                self._collection = self._client.get_or_create_collection(
                    name=self.name,
                    metadata={"description": self.description}
                )
                logger.info(f"Chroma vector store initialized: {self.name}")
                return True

            elif self.backend == "qdrant":
                from qdrant_client import QdrantClient
                from qdrant_client.models import Distance, VectorParams

                self._client = QdrantClient(path=self.persist_directory)
                collections = self._client.get_collections().collections
                exists = any(c.name == self.name for c in collections)

                if not exists:
                    self._client.create_collection(
                        collection_name=self.name,
                        vectors_config=VectorParams(size=384, distance=Distance.COSINE)
                    )
                    logger.info(f"Created Qdrant collection: {self.name}")
                else:
                    logger.info(f"Using existing Qdrant collection: {self.name}")

                return True

            else:
                logger.error(f"Unsupported backend: {self.backend}")
                return False

        except Exception as e:
            logger.error(f"Failed to initialize vector store: {e}")
            return False

    async def close(self) -> None:
        """关闭连接，释放资源"""
        if self.backend == "qdrant" and self._client:
            try:
                self._client.close()
            except Exception as e:
                logger.warning(f"Error closing Qdrant client: {e}")

    async def add(self, entry: KnowledgeEntry) -> bool:
        """添加知识条目到向量数据库"""
        if not self._collection and self.backend == "chroma":
            logger.warning("Vector store not initialized")
            return False

        embedding = await self._get_embedding(entry.content)
        if embedding is None:
            return False

        try:
            async with self._lock:
                if self.backend == "chroma":
                    self._collection.add(
                        ids=[entry.id],
                        embeddings=[embedding],
                        documents=[entry.content],
                        metadatas=[{
                            **entry.metadata,
                            "source": entry.source,
                            "confidence": entry.confidence,
                            "created_at": entry.created_at.isoformat(),
                            "updated_at": entry.updated_at.isoformat()
                        }]
                    )
                    return True

                elif self.backend == "qdrant":
                    from qdrant_client.models import PointStruct

                    self._client.upsert(
                        collection_name=self.name,
                        points=[
                            PointStruct(
                                id=entry.id,
                                vector=embedding,
                                payload={
                                    "content": entry.content,
                                    "metadata": entry.metadata,
                                    "source": entry.source,
                                    "confidence": entry.confidence,
                                    "created_at": entry.created_at.isoformat(),
                                    "updated_at": entry.updated_at.isoformat()
                                }
                            )
                        ]
                    )
                    return True

        except Exception as e:
            logger.warning(f"Failed to add entry {entry.id}: {e}")
            return False

        return False

    async def search(self, query: str, top_k: int = 5) -> List[KnowledgeEntry]:
        """语义搜索"""
        if not self._collection and self.backend == "chroma":
            logger.warning("Vector store not initialized")
            return []

        embedding = await self._get_embedding(query)
        if embedding is None:
            return []

        try:
            async with self._lock:
                if self.backend == "chroma":
                    results = self._collection.query(
                        query_embeddings=[embedding],
                        n_results=top_k
                    )

                    entries = []
                    if results["ids"] and results["ids"][0]:
                        for i, entry_id in enumerate(results["ids"][0]):
                            metadata = results["metadatas"][0][i]
                            entries.append(self._metadata_to_entry(
                                entry_id,
                                results["documents"][0][i],
                                metadata
                            ))
                    return entries

                elif self.backend == "qdrant":
                    results = self._client.search(
                        collection_name=self.name,
                        query_vector=embedding,
                        limit=top_k
                    )

                    entries = []
                    for result in results:
                        payload = result.payload
                        entries.append(self._metadata_to_entry(
                            result.id,
                            payload.get("content", ""),
                            payload
                        ))
                    return entries

        except Exception as e:
            logger.warning(f"Search failed: {e}")
            return []

        return []

    async def get(self, entry_id: str) -> Optional[KnowledgeEntry]:
        """根据ID获取条目"""
        if not self._collection and self.backend == "chroma":
            logger.warning("Vector store not initialized")
            return None

        try:
            if self.backend == "chroma":
                result = self._collection.get(ids=[entry_id])

                if result["ids"] and result["ids"][0]:
                    metadata = result["metadatas"][0]
                    return self._metadata_to_entry(
                        result["ids"][0],
                        result["documents"][0],
                        metadata
                    )

            elif self.backend == "qdrant":
                results = self._client.retrieve(
                    collection_name=self.name,
                    ids=[entry_id]
                )

                if results:
                    payload = results[0].payload
                    return self._metadata_to_entry(
                        results[0].id,
                        payload.get("content", ""),
                        payload
                    )

        except Exception as e:
            logger.warning(f"Failed to get entry {entry_id}: {e}")

        return None

    async def update(self, entry_id: str, updates: Dict[str, Any]) -> bool:
        """更新条目（先删后增）"""
        entry = await self.get(entry_id)
        if not entry:
            return False

        entry.content = updates.get("content", entry.content)
        entry.metadata = {**entry.metadata, **updates.get("metadata", {})}
        entry.updated_at = datetime.now()
        entry.confidence = updates.get("confidence", entry.confidence)

        await self.delete(entry_id)
        return await self.add(entry)

    async def delete(self, entry_id: str) -> bool:
        """删除条目"""
        if (self.backend == "chroma" and not self._collection) or \
           (self.backend == "qdrant" and not self._client):
            return False

        try:
            if self.backend == "chroma":
                self._collection.delete(ids=[entry_id])
                return True
            elif self.backend == "qdrant":
                from qdrant_client.models import PointIdsList
                self._client.delete(
                    collection_name=self.name,
                    points_selector=PointIdsList(ids=[entry_id])
                )
                return True
        except Exception as e:
            logger.warning(f"Failed to delete entry {entry_id}: {e}")

        return False

    async def clear(self) -> bool:
        """清空数据库"""
        if not self._client:
            return False

        try:
            if self.backend == "chroma":
                self._client.delete_collection(name=self.name)
                self._collection = self._client.get_or_create_collection(
                    name=self.name,
                    metadata={"description": self.description}
                )
                return True
            elif self.backend == "qdrant":
                self._client.delete_collection(collection_name=self.name)
                from qdrant_client.models import Distance, VectorParams
                self._client.create_collection(
                    collection_name=self.name,
                    vectors_config=VectorParams(size=384, distance=Distance.COSINE)
                )
                return True
        except Exception as e:
            logger.warning(f"Failed to clear collection: {e}")

        return False

    async def count(self) -> int:
        """获取条目数量"""
        try:
            if self.backend == "chroma" and self._collection:
                return self._collection.count()
            elif self.backend == "qdrant" and self._client:
                return self._client.count(collection_name=self.name).count
        except Exception as e:
            logger.warning(f"Failed to count: {e}")

        return 0

    async def add_batch(self, entries: List[KnowledgeEntry]) -> int:
        """批量添加条目（使用底层批量接口提升性能）"""
        if not entries:
            return 0

        valid_entries = []
        embeddings = []
        for entry in entries:
            emb = await self._get_embedding(entry.content)
            if emb is not None:
                valid_entries.append(entry)
                embeddings.append(emb)

        if not valid_entries:
            return 0

        try:
            async with self._lock:
                if self.backend == "chroma":
                    ids = [e.id for e in valid_entries]
                    docs = [e.content for e in valid_entries]
                    metas = [{
                        **e.metadata,
                        "source": e.source,
                        "confidence": e.confidence,
                        "created_at": e.created_at.isoformat(),
                        "updated_at": e.updated_at.isoformat()
                    } for e in valid_entries]

                    self._collection.add(
                        ids=ids,
                        embeddings=embeddings,
                        documents=docs,
                        metadatas=metas
                    )
                    return len(valid_entries)

                elif self.backend == "qdrant":
                    from qdrant_client.models import PointStruct
                    points = []
                    for entry, emb in zip(valid_entries, embeddings):
                        points.append(PointStruct(
                            id=entry.id,
                            vector=emb,
                            payload={
                                "content": entry.content,
                                "metadata": entry.metadata,
                                "source": entry.source,
                                "confidence": entry.confidence,
                                "created_at": entry.created_at.isoformat(),
                                "updated_at": entry.updated_at.isoformat()
                            }
                        ))
                    self._client.upsert(collection_name=self.name, points=points)
                    return len(points)

        except Exception as e:
            logger.warning(f"Batch add failed: {e}")
            # 降级为逐个添加
            success = 0
            for entry in valid_entries:
                if await self.add(entry):
                    success += 1
            return success

        return 0

    def _metadata_to_entry(self, entry_id: str, content: str, metadata: Dict) -> KnowledgeEntry:
        """从元数据构建 KnowledgeEntry 对象（处理日期解析异常）"""
        def parse_datetime(key: str) -> datetime:
            val = metadata.get(key)
            if val:
                try:
                    return datetime.fromisoformat(val)
                except (ValueError, TypeError):
                    pass
            return datetime.now()

        return KnowledgeEntry(
            id=entry_id,
            content=content,
            metadata=metadata,
            created_at=parse_datetime("created_at"),
            updated_at=parse_datetime("updated_at"),
            source=metadata.get("source", "unknown"),
            confidence=metadata.get("confidence", 1.0)
        )

    @staticmethod
    def create_entry(
        content: str,
        metadata: Dict[str, Any] = None,
        source: str = "unknown",
        confidence: float = 1.0
    ) -> KnowledgeEntry:
        """创建知识条目的便捷方法"""
        now = datetime.now()
        return KnowledgeEntry(
            id=str(uuid.uuid4()),
            content=content,
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
            source=source,
            confidence=confidence
        )