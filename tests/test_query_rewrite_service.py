"""QueryRewriteService 单元测试（假 LLM，结构化输出，离线运行）。"""

from __future__ import annotations

import unittest
from unittest import IsolatedAsyncioTestCase as TestCase
from unittest.mock import AsyncMock

from app.application.services.query_rewrite_service import (
    QueryRewriteOutput,
    QueryRewriteService,
)


def _service(llm_client) -> QueryRewriteService:
    return QueryRewriteService(llm_client=llm_client)


class QueryRewriteServiceTests(TestCase):
    async def test_structured_output_mapped_to_rewrite(self) -> None:
        llm = AsyncMock()
        llm.generate_structured = AsyncMock(
            return_value=QueryRewriteOutput(
                queries=["vitamin C content of apples", "apple nutrition facts"],
                keywords=["apple", "vitamin"],
            )
        )
        service = _service(llm)

        rewrite = await service.rewrite("苹果维C")

        self.assertEqual(["vitamin C content of apples", "apple nutrition facts"], rewrite.queries)
        self.assertEqual(["apple", "vitamin"], rewrite.keywords)
        self.assertEqual("apple vitamin", rewrite.sparse_text)

    async def test_no_keywords_falls_back_to_first_variant_for_sparse(self) -> None:
        llm = AsyncMock()
        llm.generate_structured = AsyncMock(
            return_value=QueryRewriteOutput(queries=["apple vitamin C"], keywords=[])
        )
        service = _service(llm)

        rewrite = await service.rewrite("苹果维C")

        self.assertEqual([], rewrite.keywords)
        self.assertEqual("apple vitamin C", rewrite.sparse_text)

    async def test_whitespace_only_variants_fall_back_to_the_raw_query(self) -> None:
        """schema 的 min_length=1 挡不住空白字符串：queries 全空白时退回原始
        查询，否则 sparse_text 的 queries[0] 会 IndexError 把 /search 打成 500。"""
        llm = AsyncMock()
        llm.generate_structured = AsyncMock(
            return_value=QueryRewriteOutput(queries=["   ", ""], keywords=[])
        )
        service = _service(llm)

        rewrite = await service.rewrite("苹果维C")

        self.assertEqual(["苹果维C"], rewrite.queries)
        self.assertEqual("苹果维C", rewrite.sparse_text)

    async def test_whitespace_keywords_are_dropped(self) -> None:
        llm = AsyncMock()
        llm.generate_structured = AsyncMock(
            return_value=QueryRewriteOutput(queries=["q"], keywords=[" ", "apple", ""])
        )
        service = _service(llm)

        rewrite = await service.rewrite("苹果维C")

        self.assertEqual(["apple"], rewrite.keywords)
        self.assertEqual("apple", rewrite.sparse_text)

    async def test_llm_error_propagates(self) -> None:
        llm = AsyncMock()
        llm.generate_structured = AsyncMock(side_effect=RuntimeError("endpoint down"))
        service = _service(llm)

        # 刻意不吞错：结构化输出失败必须显式暴露，而不是悄悄退化
        with self.assertRaises(RuntimeError):
            await service.rewrite("苹果维C")


if __name__ == "__main__":
    unittest.main()
