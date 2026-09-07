"""向量仓储端口。"""

from __future__ import annotations

from typing import Protocol


class VectorRepository(Protocol):
    """Qdrant 等向量库的存储与单路检索能力。

    实现只返回框架无关的 dict（chunk payload + score），不向外泄露
    具体向量库的类型。检索策略（融合、rerank）不属于本端口，由上层编排。
    """

    async def ensure_collection(self) -> None:
        """幂等创建 collection；已存在时校验配置一致性。"""
        ...

    async def upsert_chunks(
        self,
        *,
        document_id: str,
        document_name: str,
        chunks: list[str],
        vectors: list[list[float]],
    ) -> int:
        """写入一个文档的全部分块，返回写入的点数。"""
        ...

    async def search_by_dense(self, *, dense_vector: list[float], top_k: int) -> list[dict]:
        """稠密向量检索（语义路），score 为余弦相似度。"""
        ...

    async def search_by_sparse(self, *, query_text: str, top_k: int) -> list[dict]:
        """稀疏关键词检索（BM25 路），score 为 BM25 分数。"""
        ...

    async def get_document_chunks(self, *, document_id: str) -> list[dict]:
        """取回一个文档的全部分块，按 chunk_index 升序。"""
        ...

    async def get_chunk(self, *, document_id: str, chunk_index: int) -> dict | None:
        """按坐标精确取一个分块（含 document_name 与 text）；点不存在返回 None。

        出题 worker 手上只有坐标，不需要 scroll 整篇。
        """
        ...

    async def delete_document(self, document_id: str) -> None:
        """删除一个文档的全部向量。"""
        ...

    async def close(self) -> None:
        """释放底层连接。"""
        ...


__all__ = ["VectorRepository"]
