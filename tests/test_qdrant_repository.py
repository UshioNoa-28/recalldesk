"""QdrantRepository 集成测试（需要本地 Qdrant，连不上则跳过）。"""

from __future__ import annotations

import unittest

import pytest
from qdrant_client import AsyncQdrantClient

from app.infrastructure.qdrant_repository import QdrantRepository

pytestmark = pytest.mark.integration

URL = "http://127.0.0.1:6335"
COLLECTION = "test_qdrant_repo"
DIM = 8

# 三个 chunk 的 dense 向量取三维单位向量，互不相似，方便断言
VECTORS = [
    [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
]
CHUNKS = [
    "苹果 发布 新款 手机",
    "香蕉 营养 维生素 丰富",
    "华为 电脑 屏幕 很 好",
]


def _server_alive() -> bool:
    """真发一次请求探活：只 new 一个 client 是不连网的，服务挂了会一路报错而不是跳过。"""

    try:
        import asyncio

        async def _ping() -> bool:
            client = AsyncQdrantClient(url=URL, check_compatibility=False, timeout=3)
            try:
                await client.get_collections()
            finally:
                await client.close()
            return True

        return asyncio.run(_ping())
    except Exception:
        return False


@unittest.skipUnless(_server_alive(), f"本地 Qdrant ({URL}) 不可用")
class QdrantRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        raw = AsyncQdrantClient(url=URL, check_compatibility=False, timeout=3)
        if await raw.collection_exists(COLLECTION):
            await raw.delete_collection(COLLECTION)
        await raw.close()

        self.repo = QdrantRepository(url=URL, collection=COLLECTION, embedding_dim=DIM)
        await self.repo.ensure_collection()

    async def asyncTearDown(self) -> None:
        await self.repo.close()

    # ---- collection ----

    async def test_ensure_collection_is_idempotent(self) -> None:
        await self.repo.ensure_collection()  # 重复调用不报错

    async def test_ensure_collection_rejects_dim_mismatch(self) -> None:
        with self.assertRaises(ValueError):
            await QdrantRepository(
                url=URL,
                collection=COLLECTION,
                embedding_dim=DIM + 1,
            ).ensure_collection()

    # ---- 写入 ----

    async def test_upsert_chunks_rejects_mismatched_lengths(self) -> None:
        with self.assertRaises(ValueError):
            await self.repo.upsert_chunks(
                document_id="doc-1",
                document_name="a.txt",
                chunks=CHUNKS,
                vectors=VECTORS[:2],
            )

    async def test_upsert_rejects_wrong_dim(self) -> None:
        with self.assertRaises(ValueError):
            await self.repo.upsert_chunks(
                document_id="doc-1",
                document_name="a.txt",
                chunks=CHUNKS[:1],
                vectors=[[0.1] * (DIM - 1)],
            )

    async def test_upsert_is_idempotent_when_chunk_count_shrinks(self) -> None:
        document_id = "doc-1"
        await self.repo.upsert_chunks(
            document_id=document_id,
            document_name="a.txt",
            chunks=CHUNKS,
            vectors=VECTORS,
        )
        # 重新索引：只写 2 块 -> 旧的第 3 块不能残留
        await self.repo.upsert_chunks(
            document_id=document_id,
            document_name="a.txt",
            chunks=CHUNKS[:2],
            vectors=VECTORS[:2],
        )

        raw = AsyncQdrantClient(url=URL, check_compatibility=False, timeout=3)
        count = (await raw.count(COLLECTION)).count
        await raw.close()
        self.assertEqual(2, count)

    # ---- 检索（单路） ----

    async def test_search_by_dense_returns_traced_result(self) -> None:
        await self.repo.upsert_chunks(
            document_id="doc-1",
            document_name="a.txt",
            chunks=CHUNKS,
            vectors=VECTORS,
        )

        results = await self.repo.search_by_dense(dense_vector=VECTORS[1], top_k=2)

        self.assertEqual(2, len(results))
        top = results[0]
        self.assertEqual("doc-1", top["document_id"])
        self.assertEqual("a.txt", top["document_name"])
        self.assertEqual(1, top["chunk_index"])
        self.assertEqual(3, top["chunk_count"])
        self.assertEqual("香蕉 营养 维生素 丰富", top["text"])
        self.assertIn("point_id", top)
        # 余弦相似度，0~1
        self.assertGreater(top["score"], 0.5)

    async def test_search_by_sparse_hits_keyword(self) -> None:
        await self.repo.upsert_chunks(
            document_id="doc-1",
            document_name="a.txt",
            chunks=CHUNKS,
            vectors=VECTORS,
        )

        results = await self.repo.search_by_sparse(query_text="香蕉 营养", top_k=3)

        # 中文 multilingual tokenizer 生效：能按词命中而不是整句一个 token
        self.assertEqual(1, results[0]["chunk_index"])
        self.assertGreater(results[0]["score"], 0.0)

    async def test_search_by_sparse_without_hit_returns_empty(self) -> None:
        await self.repo.upsert_chunks(
            document_id="doc-1",
            document_name="a.txt",
            chunks=CHUNKS,
            vectors=VECTORS,
        )

        results = await self.repo.search_by_sparse(query_text="完全不相关的词", top_k=3)

        self.assertEqual([], results)

    # ---- 取回分块 ----

    async def test_get_document_chunks_sorted_and_cleared_after_delete(self) -> None:
        await self.repo.upsert_chunks(
            document_id="doc-1", document_name="a.txt", chunks=CHUNKS, vectors=VECTORS,
        )

        chunks = await self.repo.get_document_chunks(document_id="doc-1")

        self.assertEqual([0, 1, 2], [c["chunk_index"] for c in chunks])
        self.assertTrue(all(c["point_id"] for c in chunks))
        self.assertEqual("香蕉 营养 维生素 丰富", chunks[1]["text"])

        await self.repo.delete_document("doc-1")
        self.assertEqual([], await self.repo.get_document_chunks(document_id="doc-1"))

    async def test_get_chunk_reads_a_point_by_coordinate(self) -> None:
        """出题 worker 手上只有坐标：点 id 是坐标的纯函数，所以不用 scroll。"""

        await self.repo.upsert_chunks(
            document_id="doc-1", document_name="a.txt", chunks=CHUNKS, vectors=VECTORS,
        )

        chunk = await self.repo.get_chunk(document_id="doc-1", chunk_index=1)

        self.assertEqual("香蕉 营养 维生素 丰富", chunk["text"])
        self.assertEqual("a.txt", chunk["document_name"])
        self.assertEqual(1, chunk["chunk_index"])
        self.assertEqual(3, chunk["chunk_count"])
        # 和 scroll 出来的是同一个点：写入与按坐标回查共用一处 id 计算
        scrolled = await self.repo.get_document_chunks(document_id="doc-1")
        self.assertEqual(scrolled[1]["point_id"], chunk["point_id"])

    async def test_get_chunk_returns_none_for_unknown_coordinate(self) -> None:
        self.assertIsNone(await self.repo.get_chunk(document_id="ghost", chunk_index=0))

    # ---- 删除 ----

    async def test_delete_document_removes_all_points(self) -> None:
        await self.repo.upsert_chunks(
            document_id="doc-1",
            document_name="a.txt",
            chunks=CHUNKS,
            vectors=VECTORS,
        )
        await self.repo.delete_document("doc-1")

        raw = AsyncQdrantClient(url=URL, check_compatibility=False, timeout=3)
        count = (await raw.count(COLLECTION)).count
        await raw.close()
        self.assertEqual(0, count)

    async def test_delete_document_is_noop_for_unknown_id(self) -> None:
        await self.repo.delete_document("not-exist")  # 不报错即可


if __name__ == "__main__":
    unittest.main()
