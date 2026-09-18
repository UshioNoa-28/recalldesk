"""chunk 检索存储端口：dense + sparse 两路检索与分块原文读取（现由 Neo4j 实现）。

前身为 VectorRepository（Qdrant 实现），接口形状不变，语义换血一处：

- Qdrant payload 曾是分块文本的"唯一权威"；现在 Neo4j 里的 Chunk.text
  只是**可丢弃的派生副本**——真权威是磁盘原始文件 + 重索引链路。
  图/索引库整个删掉都不心疼，reindex 一键重灌（用户拍板：无需兼容）。
- BM25 全文索引物理上要求文本住在引擎里，所以 text 存在 Chunk 节点属性上，
  供 search_by_sparse / get_chunk / get_document_chunks 直接返回。

命中 dict 的统一形状（两路一致，融合与回填只认这些键）：
{point_id, document_id, document_name, chunk_index, chunk_count, text, score}
point_id 是 RRF 合并键，口径固定为 f"{document_id}:{chunk_index}"。

融合（RRF）、改写、重排等编排不属于本端口，归 SearchService。
"""

from __future__ import annotations

from typing import Protocol


class ChunkIndex(Protocol):
    """chunk 级存储与单路检索原语（dense / sparse 各一路）。"""

    async def ensure_indexes(self) -> None:
        """幂等创建向量/全文索引与约束；引擎不可用或维度不符时抛错（组装期 fail fast）。"""
        ...

    async def upsert_chunks(
        self,
        *,
        document_id: str,
        document_name: str,
        chunks: list[str],
        vectors: list[list[float]],
    ) -> int:
        """整篇替换一个文档的可检索块，返回写入块数（先清旧块，重复索引幂等）。"""
        ...

    async def search_by_dense(self, *, dense_vector: list[float], top_k: int) -> list[dict]:
        """稠密向量检索（语义路），score 为余弦相似度，0~1。"""
        ...

    async def search_by_sparse(self, *, query_text: str, top_k: int) -> list[dict]:
        """关键词检索（BM25 路，全文索引），score 为 BM25 分数，无界。"""
        ...

    async def get_document_chunks(self, *, document_id: str) -> list[dict]:
        """取回一个文档的全部分块，按 chunk_index 升序。"""
        ...

    async def get_chunk(self, *, document_id: str, chunk_index: int) -> dict | None:
        """按坐标精确取一个分块（含 document_name 与 text）；块不存在返回 None。

        出题 worker 手上只有坐标，不需要拉整篇。
        """
        ...

    async def delete_document(self, *, document_id: str) -> None:
        """删除一个文档的全部块（没有就是空操作，幂等）。"""
        ...

    async def close(self) -> None:
        """释放底层连接。"""
        ...


__all__ = ["ChunkIndex"]
