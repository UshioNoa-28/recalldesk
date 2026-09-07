"""检索编排服务：多路召回与 RRF 融合。

框架无关：只依赖 ports（VectorRepository / EmbeddingClient），
不感知 Qdrant / httpx / 任何具体实现，也不引入检索框架。

多路形态：
- rewriter 未接入：dense 原查询 1 路 + sparse 1 路
- rewriter 接入：dense = 原查询 + N 个改写变体（保底原查询），
  sparse 仍是单路关键词 —— 全部 asyncio.gather 并行，RRF 融合
"""

from __future__ import annotations

import asyncio

from app.application.services.query_rewrite_service import QueryRewriteService
from app.ports.embedding_client import EmbeddingClient
from app.ports.reranker import Reranker
from app.ports.vector_repository import VectorRepository

# RRF 原论文默认值：k 越大，单路排名差对最终分数的影响越平滑（写死，不开配置位）
_RRF_K = 60


def rrf_fuse(channels: list[list[dict]], *, k: int, top_k: int) -> list[dict]:
    """Reciprocal Rank Fusion：score = sum(1 / (k + rank))，rank 从 0 计。

    每路各自按 score 降序取排名，按 point_id 合并；只出现在部分路的
    chunk 只累加那些路的贡献。返回带融合分的 chunk 列表（降序，截断到 top_k）。
    """

    fused: dict[str, dict] = {}
    for hits in channels:
        ordered = sorted(hits, key=lambda item: item["score"], reverse=True)
        for rank, item in enumerate(ordered):
            entry = fused.setdefault(item["point_id"], {"item": item, "score": 0.0})
            entry["score"] += 1.0 / (k + rank)

    ranked = sorted(fused.values(), key=lambda entry: entry["score"], reverse=True)
    out: list[dict] = []
    for entry in ranked[:top_k]:
        item = dict(entry["item"])
        item["score"] = round(entry["score"], 4)
        out.append(item)
    return out


class SearchService:
    """检索编排服务（查询用例的入口）。"""

    def __init__(
        self,
        *,
        repository: VectorRepository,
        embedding_client: EmbeddingClient,
        default_top_k: int,
        rewriter: QueryRewriteService | None = None,
        reranker: Reranker | None = None,
        rerank_top_n: int = 20,
    ) -> None:
        self._repository = repository
        self._embedding_client = embedding_client
        self._rewriter = rewriter
        self._reranker = reranker
        self._rerank_top_n = rerank_top_n
        self._default_top_k = default_top_k

    @property
    def rewrite_enabled(self) -> bool:
        """改写这条路是否真的接上了（评测 run 要把它记进配置快照）。"""

        return self._rewriter is not None

    @property
    def rerank_enabled(self) -> bool:
        """重排这条路是否真的接上了（评测 run 要把它记进配置快照）。"""

        return self._reranker is not None

    async def search(self, query: str, *, top_k: int | None = None) -> list[dict]:
        """多路并行召回 + RRF 融合（+ 可选 LLM 重排），返回带溯源字段的 chunk 列表。"""

        top_k = top_k or self._default_top_k
        # 有 reranker 时先取更多候选（rerank_top_n），重排后再截回 top_k
        candidate_limit = top_k
        if self._reranker is not None:
            candidate_limit = max(top_k, self._rerank_top_n)

        dense_texts = [query]
        sparse_texts = [query]
        if self._rewriter is not None:
            rewrite = await self._rewriter.rewrite(query)
            dense_texts = [query, *rewrite.queries]  # 原查询保底 + 变体
            sparse_texts = [rewrite.sparse_text]

        # dense 并发embed所有重写的 query 
        dense_vectors = await asyncio.gather(
            *(self._embedding_client.embed_one(text) for text in dense_texts)
        )
        # 并发查询 所有的rewrite query 和 关键词
        results = await asyncio.gather(
            *(
                self._repository.search_by_dense(dense_vector=vector, top_k=candidate_limit)
                for vector in dense_vectors
            ),
            *(
                self._repository.search_by_sparse(query_text=text, top_k=candidate_limit)
                for text in sparse_texts
            ),
        )
        dense_results, sparse_results = (
            results[: len(dense_texts)],
            results[len(dense_texts) :],
        )
        fused = rrf_fuse(
            [*dense_results, *sparse_results], k=_RRF_K, top_k=candidate_limit
        )# RRF
        if self._reranker is not None:
            fused = await self._reranker.rerank(query=query, candidates=fused, top_k=top_k)
        else:
            fused = fused[:top_k] # 返回topk结果 
        return [
            {
                "document_id": item["document_id"],
                "document_name": item["document_name"],
                "chunk_index": item["chunk_index"],
                "chunk_count": item["chunk_count"],
                "score": item["score"],
                "text": item["text"],
            }
            for item in fused
        ]


__all__ = ["SearchService", "rrf_fuse"]
