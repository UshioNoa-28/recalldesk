"""OllamaQwen3Reranker 单元测试（fake httpx，不打真实 Ollama）。"""

from __future__ import annotations

import math
import unittest
from unittest import IsolatedAsyncioTestCase

import httpx

from app.infrastructure.ollama_qwen3_reranker import (
    OllamaQwen3Reranker,
    _yes_probability,
)


def _generate_response(yes_logprob: float | None, no_logprob: float | None) -> dict:
    """构造 /api/generate 带 logprobs 的响应：首 token 分布里有（或没有）yes/no。"""

    top: list[dict] = []
    if yes_logprob is not None:
        top.append({"token": "yes", "logprob": yes_logprob})
    if no_logprob is not None:
        top.append({"token": "no", "logprob": no_logprob})
    top.append({"token": "<think>", "logprob": -1.2})
    return {
        "response": "<think>",
        "logprobs": [{"token": "<think>", "top_logprobs": top}],
    }


class _FakeTransport(httpx.AsyncBaseTransport):
    """按顺序返回预设响应；记录收到的请求体。"""

    def __init__(self, responses: list[dict | httpx.HTTPStatusError]) -> None:
        self._responses = list(responses)
        self.requests: list[dict] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        import json as _json

        self.requests.append(_json.loads(request.content.decode()))
        if not self._responses:
            raise AssertionError("没有更多预设响应了")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            return httpx.Response(500, request=request, text="ollama down")
        return httpx.Response(200, request=request, json=item)


class YesProbabilityTests(unittest.TestCase):
    def test_normalizes_yes_and_no(self) -> None:
        data = _generate_response(yes_logprob=math.log(0.8), no_logprob=math.log(0.1))
        self.assertAlmostEqual(0.8 / 0.9, _yes_probability(data), places=6)

    def test_only_yes_present(self) -> None:
        data = _generate_response(yes_logprob=math.log(0.5), no_logprob=None)
        self.assertAlmostEqual(1.0, _yes_probability(data), places=6)

    def test_only_no_present(self) -> None:
        data = _generate_response(yes_logprob=None, no_logprob=math.log(0.5))
        self.assertAlmostEqual(0.0, _yes_probability(data), places=6)

    def test_missing_both_scores_zero(self) -> None:
        data = _generate_response(yes_logprob=None, no_logprob=None)
        self.assertEqual(0.0, _yes_probability(data))

    def test_missing_logprobs_scores_zero(self) -> None:
        self.assertEqual(0.0, _yes_probability({"response": "yes"}))


class OllamaQwen3RerankerTests(IsolatedAsyncioTestCase):
    def _reranker(
        self, responses: list[dict | Exception]
    ) -> tuple[OllamaQwen3Reranker, _FakeTransport]:
        transport = _FakeTransport(responses)  # type: ignore[arg-type]
        client = httpx.AsyncClient(transport=transport)
        return (
            OllamaQwen3Reranker(
                base_url="http://ollama.test",
                model="qwen3-reranker",
                client=client,
            ),
            transport,
        )

    def _candidate(self, point_id: str) -> dict:
        return {"point_id": point_id, "text": f"候选 {point_id}"}

    async def test_reranks_by_yes_probability(self) -> None:
        # 三个候选：p-1 相关、p-2 无关、p-3 中等
        reranker, transport = self._reranker(
            [
                _generate_response(yes_logprob=math.log(0.9), no_logprob=math.log(0.05)),
                _generate_response(yes_logprob=math.log(0.05), no_logprob=math.log(0.9)),
                _generate_response(yes_logprob=math.log(0.5), no_logprob=math.log(0.5)),
            ]
        )
        try:
            results = await reranker.rerank(
                query="查询",
                candidates=[self._candidate("p-1"), self._candidate("p-2"), self._candidate("p-3")],
                top_k=2,
            )
        finally:
            await reranker.close()

        self.assertEqual(["p-1", "p-3"], [item["point_id"] for item in results])
        self.assertEqual(2, len(results))  # top_k 截断
        # 分数是 P(yes)：p-1 = 0.9/0.95
        self.assertAlmostEqual(0.9474, results[0]["score"], places=4)

        # 请求形状：raw 模板 + logprobs + 只生成 1 个 token
        first = transport.requests[0]
        self.assertEqual("qwen3-reranker", first["model"])
        self.assertTrue(first["raw"])
        self.assertTrue(first["logprobs"])
        self.assertEqual(1, first["options"]["num_predict"])
        self.assertIn("<Query>: 查询", first["prompt"])
        self.assertIn("<Document>: 候选 p-1", first["prompt"])

    async def test_empty_candidates_return_empty(self) -> None:
        reranker, transport = self._reranker([])
        try:
            results = await reranker.rerank(query="查询", candidates=[], top_k=5)
        finally:
            await reranker.close()
        self.assertEqual([], results)
        self.assertEqual([], transport.requests)

    async def test_ollama_error_propagates(self) -> None:
        """rerank 失败显式报错（与改写一致：不静默降级）。"""

        reranker, _ = self._reranker([RuntimeError("ollama down")])
        try:
            with self.assertRaises(httpx.HTTPStatusError):
                await reranker.rerank(
                    query="查询",
                    candidates=[self._candidate("p-1")],
                    top_k=1,
                )
        finally:
            await reranker.close()

    async def test_bad_response_scores_zero_but_keeps_candidate(self) -> None:
        """单个候选的响应缺 logprobs：按 0 分留在末尾，不打断整批。"""

        reranker, _ = self._reranker(
            [
                _generate_response(yes_logprob=math.log(0.9), no_logprob=math.log(0.05)),
                {"response": "yes"},  # 没有 logprobs 字段
            ]
        )
        try:
            results = await reranker.rerank(
                query="查询",
                candidates=[self._candidate("p-1"), self._candidate("p-2")],
                top_k=2,
            )
        finally:
            await reranker.close()

        self.assertEqual(["p-1", "p-2"], [item["point_id"] for item in results])
        self.assertEqual(0.0, results[1]["score"])

    async def test_original_fields_are_preserved(self) -> None:
        reranker, _ = self._reranker(
            [_generate_response(yes_logprob=math.log(0.9), no_logprob=math.log(0.05))]
        )
        candidate = {
            "point_id": "p-1",
            "document_id": "doc-1",
            "chunk_index": 0,
            "text": "候选文本",
            "score": 0.0315,  # 原 RRF 分，应被 rerank 分替换
        }
        try:
            (result,) = await reranker.rerank(
                query="查询", candidates=[candidate], top_k=1
            )
        finally:
            await reranker.close()

        self.assertEqual("doc-1", result["document_id"])
        self.assertEqual(0, result["chunk_index"])
        self.assertNotEqual(0.0315, result["score"])


if __name__ == "__main__":
    unittest.main()
