"""索引编排服务：分块、embedding、向量写入；以及删除一个文档的向量。"""

from __future__ import annotations

from app.application.services.split_service import SplitService
from app.ports.embedding_client import EmbeddingClient
from app.ports.vector_repository import VectorRepository


class EmptyContentError(ValueError):
    """文档切不出任何分块：内容本身的问题，重试多少次都不会变好。"""


class IndexingService:
    """索引编排服务（索引用例的入口）。"""

    def __init__(
        self,
        *,
        repository: VectorRepository,
        embedding_client: EmbeddingClient,
        split_service: SplitService,
    ) -> None:
        self._repository = repository
        self._embedding_client = embedding_client
        self._split_service = split_service

    async def ingest(self, document_id: str, name: str, text: str) -> int:
        chunks = self._split_service.split(name, text)
        if not chunks:
            raise EmptyContentError("文档没有可索引的内容")
        vectors = await self._embedding_client.embed(chunks)
        return await self._repository.upsert_chunks(
            document_id=document_id,
            document_name=name,
            chunks=chunks,
            vectors=vectors,
        )

    async def delete(self, document_id: str) -> None:
        """删掉一个文档的全部向量：按 document_id 过滤，点不在就是空操作。"""

        await self._repository.delete_document(document_id)


__all__ = ["EmptyContentError", "IndexingService"]
