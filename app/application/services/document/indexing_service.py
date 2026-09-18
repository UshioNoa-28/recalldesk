"""索引编排服务：分块、embedding、检索索引写入；以及删除一个文档的索引块。"""

from __future__ import annotations

from app.application.services.document.split_service import SplitService
from app.ports.chunk_index import ChunkIndex
from app.ports.model_clients.embedding_client import EmbeddingClient


class EmptyContentError(ValueError):
    """文档切不出任何分块：内容本身的问题，重试多少次都不会变好。"""


class IndexingService:
    """索引编排服务（索引用例的入口）。"""

    def __init__(
        self,
        *,
        index: ChunkIndex,
        embedding_client: EmbeddingClient,
        split_service: SplitService,
    ) -> None:
        self._index = index
        self._embedding_client = embedding_client
        self._split_service = split_service

    async def ingest(self, document_id: str, name: str, text: str) -> int:
        chunks = self._split_service.split(name, text)
        if not chunks:
            raise EmptyContentError("文档没有可索引的内容")
        vectors = await self._embedding_client.embed(chunks)
        return await self._index.upsert_chunks(
            document_id=document_id,
            document_name=name,
            chunks=chunks,
            vectors=vectors,
        )

    async def delete(self, document_id: str) -> None:
        """删掉一个文档的全部索引块：按 document_id 过滤，块不在就是空操作。

        keyword-only 传参是端口签名（chunk_index.delete_document(*, document_id)）
        定的——位置传参会在真实 adapter 上 TypeError（活体踩过：delete 任务
        无限重投而单测全绿，因为假索引当年收位置参）。
        """

        await self._index.delete_document(document_id=document_id)


__all__ = ["EmptyContentError", "IndexingService"]
