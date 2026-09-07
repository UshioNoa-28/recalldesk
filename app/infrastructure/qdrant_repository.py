"""Qdrant 向量仓储：原生 AsyncQdrantClient 实现，不依赖 llama-index。

职责边界：只提供存储能力原语（写入、单路检索、删除），
检索策略（两路融合、rerank）由上层 SearchService 编排，不属于这里。

- ensure_collection：幂等建 collection（dense 向量 + 服务端 BM25 稀疏向量）
- upsert_chunks：写入一个文档的全部分块（dense 向量由调用方算好，稀疏直接发文本
  给服务端 BM25 推理）；同文档重复写入会先清旧块，天然幂等
- search_by_dense / search_by_sparse：单路检索，返回框架无关的 chunk dict
- get_document_chunks：按文档取回全部分块（scroll 翻页）
- delete_document：按 document_id 清除该文档全部向量

版本要求：server >= 1.15.2（服务端 BM25），本项目 server 为 1.18.3，已实测。

服务端 BM25 两个必须注意的配置（来自官方 Full-Text Search 文档）：
1. sparse 向量必须配 modifier=IDF；
2. BM25 默认按英文处理（word tokenizer 按空格切分，中文整句会变成一个 token），
   必须给 Document 传 options={"tokenizer": "multilingual"}，且入库与查询用同一套。
"""

from __future__ import annotations

import logging
import uuid

from qdrant_client import AsyncQdrantClient, models

from app.ports.vector_repository import VectorRepository

logger = logging.getLogger(__name__)

# 命名向量的固定名字（collection 内部约定，不对外暴露）
DENSE_VECTOR = "dense"
SPARSE_VECTOR = "sparse"

# 服务端 BM25 推理模型名与文本处理选项（入库/查询两侧必须一致）
BM25_MODEL = "Qdrant/bm25"
BM25_OPTIONS: dict = {"tokenizer": "multilingual"}

# chunk 的 point id 生成命名空间（确定性 id：同一文档同一序号 -> 同一 id）
_POINT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "anna-rag:chunk")


def _point_id(document_id: str, chunk_index: int) -> str:
    """chunk 坐标 -> Qdrant 点 id。写入与按坐标回查必须走同一处，否则读不到。"""

    return str(uuid.uuid5(_POINT_NAMESPACE, f"{document_id}:{chunk_index}"))


class QdrantRepository(VectorRepository):
    """对 Qdrant collection 的读写封装，只认识向量和 payload。"""

    def __init__(
        self,
        *,
        url: str,
        collection: str,
        embedding_dim: int,
        api_key: str | None = None,
        timeout: float = 10.0,
        bm25_model: str = BM25_MODEL,
        bm25_options: dict | None = None,
    ) -> None:
        self._collection = collection
        self._embedding_dim = embedding_dim
        self._bm25_model = bm25_model
        self._bm25_options = bm25_options if bm25_options is not None else dict(BM25_OPTIONS)
        self._client = AsyncQdrantClient(
            url=url,
            api_key=api_key,
            check_compatibility=False,
            timeout=timeout,
        )

    # ---- collection ----

    async def ensure_collection(self) -> None:
        """幂等创建 collection；已存在时校验 dense 维度，不一致直接报错。"""

        if await self._client.collection_exists(self._collection):
            info = await self._client.get_collection(self._collection)
            size = info.config.params.vectors[DENSE_VECTOR].size
            if size != self._embedding_dim:
                raise ValueError(
                    f"collection {self._collection!r} 的 dense 维度是 {size}，"
                    f"与配置的 embedding_dim={self._embedding_dim} 不一致"
                )
            return

        await self._client.create_collection(
            self._collection,
            vectors_config={
                DENSE_VECTOR: models.VectorParams(
                    size=self._embedding_dim,
                    distance=models.Distance.COSINE,
                ),
            },
            sparse_vectors_config={
                SPARSE_VECTOR: models.SparseVectorParams(
                    modifier=models.Modifier.IDF,
                ),
            },
        )
        logger.info("已创建 collection: %s (dense=%d 维)", self._collection, self._embedding_dim)

    # ---- 写入 / 删除 ----

    async def upsert_chunks(
        self,
        *,
        document_id: str,
        document_name: str,
        chunks: list[str],
        vectors: list[list[float]],
    ) -> int:
        """写入一个文档的全部分块，返回写入的点数。

        vectors 是每个 chunk 的 dense embedding，第 i 个元素对应 chunks[i]；
        稀疏向量只传原文，由服务端 BM25 模型推理。写入前先清掉该文档旧块，
        重复索引不会残留。
        """

        if len(chunks) != len(vectors):
            raise ValueError(f"chunks 与 vectors 数量不一致: {len(chunks)} != {len(vectors)}")
        for i, vector in enumerate(vectors):
            if len(vector) != self._embedding_dim:
                raise ValueError(
                    f"vectors[{i}] 维度是 {len(vector)}，"
                    f"与 embedding_dim={self._embedding_dim} 不符"
                )
        if not chunks:
            return 0

        await self._delete_points(document_id)
        points = [
            models.PointStruct(
                id=_point_id(document_id, index),
                vector={
                    DENSE_VECTOR: vector,
                    SPARSE_VECTOR: models.Document(
                        text=chunk,
                        model=self._bm25_model,
                        options=self._bm25_options,
                    ),
                },
                payload={
                    "document_id": document_id,
                    "document_name": document_name,
                    "chunk_index": index,
                    "chunk_count": len(chunks),
                    "text": chunk,
                },
            )
            for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
        ]
        await self._client.upsert(self._collection, points=points)
        return len(points)

    async def delete_document(self, document_id: str) -> None:
        """删除一个文档的全部向量（没有向量时是空操作）。"""

        await self._delete_points(document_id)

    async def _delete_points(self, document_id: str) -> None:
        await self._client.delete(
            self._collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=document_id),
                        ),
                    ],
                ),
            ),
        )

    # ---- 检索（单路原语，融合由上层负责） ----

    async def search_by_dense(self, *, dense_vector: list[float], top_k: int) -> list[dict]:
        """稠密向量检索（语义路）。score 为余弦相似度，0~1。"""

        result = await self._client.query_points(
            self._collection,
            query=dense_vector,
            using=DENSE_VECTOR,
            limit=top_k,
            with_payload=True,
        )
        return self._to_items(result.points)

    async def search_by_sparse(self, *, query_text: str, top_k: int) -> list[dict]:
        """稀疏关键词检索（BM25 路）。score 为 BM25 分数，无界。"""

        result = await self._client.query_points(
            self._collection,
            query=models.Document(
                text=query_text,
                model=self._bm25_model,
                options=self._bm25_options,
            ),
            using=SPARSE_VECTOR,
            limit=top_k,
            with_payload=True,
        )
        return self._to_items(result.points)

    async def get_document_chunks(self, *, document_id: str) -> list[dict]:
        """取回一个文档的全部分块（scroll 翻页），按 chunk_index 升序。"""

        collected: list = []
        offset = None
        while True:
            batch, offset = await self._client.scroll(
                self._collection,
                scroll_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=document_id),
                        ),
                    ],
                ),
                limit=256,
                offset=offset,
                with_payload=True,
            )
            collected.extend(batch)
            if offset is None:
                break

        chunks = [
            {
                "point_id": str(point.id),
                "chunk_index": point.payload["chunk_index"],
                "chunk_count": point.payload["chunk_count"],
                "text": point.payload["text"],
            }
            for point in collected
        ]
        chunks.sort(key=lambda item: item["chunk_index"])
        return chunks

    async def get_chunk(self, *, document_id: str, chunk_index: int) -> dict | None:
        """按坐标精确取一个分块：点 id 是坐标的纯函数，所以不用 scroll。"""

        points = await self._client.retrieve(
            self._collection,
            ids=[_point_id(document_id, chunk_index)],
            with_payload=True,
        )
        if not points:
            return None
        payload = points[0].payload
        return {
            "point_id": str(points[0].id),
            "document_name": payload["document_name"],
            "chunk_index": payload["chunk_index"],
            "chunk_count": payload["chunk_count"],
            "text": payload["text"],
        }

    def _to_items(self, points: list) -> list[dict]:
        """把 Qdrant 返回的点映射成框架无关的 chunk dict（按 score 降序天然成立）。"""

        return [
            {
                "point_id": str(point.id),
                "document_id": point.payload["document_id"],
                "document_name": point.payload["document_name"],
                "chunk_index": point.payload["chunk_index"],
                "chunk_count": point.payload["chunk_count"],
                "score": round(float(point.score), 4),
                "text": point.payload["text"],
            }
            for point in points
        ]

    # ---- 生命周期 ----

    async def close(self) -> None:
        await self._client.close()


__all__ = ["QdrantRepository"]
