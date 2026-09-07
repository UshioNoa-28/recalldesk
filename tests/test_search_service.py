"""SearchService 单元测试（假仓储/假 embedding，纯逻辑，离线运行）。"""

from __future__ import annotations

import re
import unittest
from unittest import IsolatedAsyncioTestCase as TestCase

from app.application.services.search_service import SearchService, rrf_fuse


class _FakeSplitter:
    """按句切分的假分块器，替代真实 splitter（离线、确定性）。"""

    def split(self, text: str) -> list[str]:
        return [p for p in re.split(r"(?<=[。！？])\s*", text) if p.strip()]


def _hit(point_id: str, score: float, text: str = "内容") -> dict:
    return {
        "point_id": point_id,
        "document_id": "doc-1",
        "document_name": "a.txt",
        "chunk_index": int(point_id.split("-")[1]),
        "chunk_count": 3,
        "score": score,
        "text": text,
    }


class RrfFuseTests(TestCase):
    def test_both_channels_ranked_fuses_by_rank(self) -> None:
        dense = [_hit("p-0", 0.9), _hit("p-1", 0.5)]
        sparse = [_hit("p-1", 12.0), _hit("p-0", 3.0)]

        fused = rrf_fuse([dense, sparse], k=2, top_k=2)

        # p-0: 1/(2+0) + 1/(2+1) = 0.833；p-1: 1/(2+1) + 1/(2+0) = 0.833 -> 对称同分
        self.assertEqual(["p-0", "p-1"], [item["point_id"] for item in fused])
        self.assertEqual(fused[0]["score"], fused[1]["score"])

    def test_appear_in_one_channel_only(self) -> None:
        dense = [_hit("p-0", 0.9)]
        sparse = [_hit("p-2", 5.0)]

        fused = rrf_fuse([dense, sparse], k=2, top_k=5)

        # 各自都是本路第一：1/(2+0) = 0.5，同分
        self.assertEqual(0.5, fused[0]["score"])
        self.assertEqual(0.5, fused[1]["score"])

    def test_top_k_truncates(self) -> None:
        dense = [_hit(f"p-{i}", 1.0 - i * 0.1) for i in range(5)]
        sparse: list[dict] = []

        fused = rrf_fuse([dense, sparse], k=2, top_k=2)

        self.assertEqual(2, len(fused))
        self.assertEqual("p-0", fused[0]["point_id"])


class _FakeRepository:
    """记录调用并返回预设结果的最小仓储替身。"""

    def __init__(self, dense_hits: list[dict], sparse_hits: list[dict]) -> None:
        self.dense_hits = dense_hits
        self.sparse_hits = sparse_hits
        self.dense_call: dict | None = None
        self.sparse_call: dict | None = None

    async def search_by_dense(self, *, dense_vector: list[float], top_k: int) -> list[dict]:
        self.dense_call = {"dense_vector": dense_vector, "top_k": top_k}
        return self.dense_hits

    async def search_by_sparse(self, *, query_text: str, top_k: int) -> list[dict]:
        self.sparse_call = {"query_text": query_text, "top_k": top_k}
        return self.sparse_hits


class _FakeEmbeddingClient:
    def __init__(self, dim: int = 4) -> None:
        self.dim = dim
        self.batches: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.batches.append(texts)
        return [[float(len(t))] * self.dim for t in texts]

    async def embed_one(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]

    def close(self) -> None: ...


class _FakeReranker:
    """记录调用并把候选原样返回的替身。"""

    def __init__(self) -> None:
        self.called = False
        self.query: str | None = None
        self.candidates: list[dict] = []
        self.top_k: int | None = None

    async def rerank(self, *, query: str, candidates: list[dict], top_k: int) -> list[dict]:
        self.called = True
        self.query = query
        self.candidates = candidates
        self.top_k = top_k
        return candidates[:top_k]


class SearchServiceTests(TestCase):
    def _service(self, repository: _FakeRepository) -> SearchService:
        return SearchService(
            repository=repository,
            embedding_client=self.embedding,
            default_top_k=3,
        )

    def setUp(self) -> None:
        self.embedding = _FakeEmbeddingClient()

    async def test_search_fuses_two_channels_and_strips_internal_fields(self) -> None:
        dense = [_hit("p-0", 0.9), _hit("p-1", 0.5)]
        sparse = [_hit("p-1", 9.0), _hit("p-0", 2.0)]
        repository = _FakeRepository(dense_hits=dense, sparse_hits=sparse)
        service = self._service(repository)

        results = await service.search("香蕉 营养")

        self.assertEqual([0, 1], [r["chunk_index"] for r in results][:2])
        self.assertNotIn("point_id", results[0])
        self.assertIn("document_id", results[0])
        self.assertIn("chunk_count", results[0])
        # 两路都拿到了同一个查询向量与原文
        self.assertEqual([5.0] * 4, repository.dense_call["dense_vector"])  # len("香蕉 营养")
        self.assertEqual("香蕉 营养", repository.sparse_call["query_text"])

    async def test_search_uses_default_top_k(self) -> None:
        repository = _FakeRepository(dense_hits=[], sparse_hits=[])
        service = self._service(repository)

        await service.search("查询")

        self.assertEqual(3, repository.dense_call["top_k"])
        self.assertEqual(3, repository.sparse_call["top_k"])

    async def test_search_with_reranker_fetches_more_candidates_then_truncates(self) -> None:
        dense = [_hit(f"p-{i}", 1.0 - i * 0.1) for i in range(5)]
        repository = _FakeRepository(dense_hits=dense, sparse_hits=[])
        reranker = _FakeReranker()
        service = SearchService(
            repository=repository,
            embedding_client=self.embedding,
            default_top_k=3,
            reranker=reranker,
            rerank_top_n=5,
        )

        results = await service.search("查询")

        # 融合前按 rerank_top_n 取候选，重排后再截回 top_k
        self.assertTrue(reranker.called)
        self.assertEqual(5, repository.dense_call["top_k"])
        self.assertEqual(5, repository.sparse_call["top_k"])
        self.assertEqual(3, reranker.top_k)
        self.assertEqual(3, len(results))


if __name__ == "__main__":
    unittest.main()
