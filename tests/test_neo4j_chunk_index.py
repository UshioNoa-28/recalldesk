"""Neo4jChunkIndex adapter 测试。

离线部分（fake driver）锁住跨代契约：命中 dict 的形状与 point_id 口径
（SearchService/RRF 依赖）、Lucene 查询转义、ensure_indexes 的维度校验
（IF NOT EXISTS 会静默放过旧维度索引，这里必须 fail fast）、整篇替换的入参。
LiveIntegrationTests 连真 Neo4j（compose 起好即可，自带造数与清数），
连不上自动跳过。
"""

from __future__ import annotations

import unittest
from typing import Any, ClassVar

import pytest

from app.infrastructure.neo4j.chunk_index import (
    DENSE_INDEX,
    Neo4jChunkIndex,
    _fulltext_query,
)
from settings import settings


class _FakeResult:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.records = records


class _FakeDriver:
    """记录每次 execute_query；按 cypher 子串预设返回记录（dict 即 record）。"""

    def __init__(self, responses: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.responses = responses or {}

    async def execute_query(self, query_: str, **kwargs: Any) -> _FakeResult:
        # 第一参数名刻意用 query_：真驱动签名如此，防的就是 kwargs 里出现 query= 撞名
        self.calls.append((query_, kwargs))
        for key, records in self.responses.items():
            if key in query_:
                return _FakeResult([dict(r) for r in records])
        return _FakeResult([])

    async def close(self) -> None:
        self.calls.append(("CLOSE", {}))


def _index(driver: _FakeDriver, *, dim: int = 1024) -> Neo4jChunkIndex:
    return Neo4jChunkIndex(driver, embedding_dim=dim, analyzer="cjk")


class FulltextEscapeTests(unittest.TestCase):
    def test_terms_become_quoted_phrase_disjunction(self) -> None:
        self.assertEqual('"苹果" "维C"', _fulltext_query("苹果 维C"))

    def test_syntax_characters_stripped(self) -> None:
        # 裸 && || 等会被 Lucene 当语法解析；剥掉特殊字符后按普通词查
        self.assertEqual('"a" "b" "c"', _fulltext_query('a "b" && c++ ||'))

    def test_blank_query_yields_empty(self) -> None:
        self.assertEqual("", _fulltext_query("   "))


class EnsureIndexesTests(unittest.IsolatedAsyncioTestCase):
    async def test_creates_constraint_vector_and_fulltext(self) -> None:
        driver = _FakeDriver()
        await _index(driver).ensure_indexes()
        joined = "\n".join(q for q, _ in driver.calls)
        self.assertIn("CREATE CONSTRAINT", joined)
        self.assertIn("CREATE VECTOR INDEX", joined)
        self.assertIn("CREATE FULLTEXT INDEX", joined)
        self.assertIn("cjk", joined)

    async def test_existing_index_with_wrong_dims_fails_fast(self) -> None:
        """IF NOT EXISTS 对"存在但 512 维"的老索引静默跳过——必须在启动就炸。"""

        driver = _FakeDriver(
            responses={"SHOW VECTOR INDEXES": [{"cfg": {"vector.dimensions": 512}}]}
        )
        with self.assertRaises(RuntimeError) as exc:
            await _index(driver, dim=1024).ensure_indexes()
        self.assertIn("维度", str(exc.exception))
        self.assertFalse(any("CREATE VECTOR INDEX" in q for q, _ in driver.calls))

    async def test_existing_index_matching_dims_passes(self) -> None:
        driver = _FakeDriver(
            responses={"SHOW VECTOR INDEXES": [{"cfg": {"vector.dimensions": 1024}}]}
        )
        await _index(driver, dim=1024).ensure_indexes()
        self.assertTrue(any(f"{DENSE_INDEX} IF NOT EXISTS" in q for q, _ in driver.calls))


class UpsertTests(unittest.IsolatedAsyncioTestCase):
    async def test_replaces_document_in_one_roundtrip(self) -> None:
        driver = _FakeDriver()
        count = await _index(driver).upsert_chunks(
            document_id="d1",
            document_name="a.txt",
            chunks=["第一块", "第二块"],
            vectors=[[0.1] * 1024, [0.2] * 1024],
        )
        self.assertEqual(2, count)
        self.assertEqual(1, len(driver.calls))
        query, kwargs = driver.calls[0]
        self.assertIn("DETACH DELETE", query)  # 整篇替换的"先清"
        self.assertIn("UNWIND", query)
        rows = kwargs["rows"]
        self.assertEqual(0, rows[0]["idx"])
        self.assertEqual("第一块", rows[0]["text"])
        self.assertEqual("a.txt", rows[1]["name"])
        self.assertEqual(2, rows[1]["count"])

    async def test_dim_mismatch_rejected(self) -> None:
        driver = _FakeDriver()
        with self.assertRaises(ValueError):
            await _index(driver).upsert_chunks(
                document_id="d1",
                document_name="a",
                chunks=["x"],
                vectors=[[0.5] * 3],  # dim=1024
            )

    async def test_count_mismatch_rejected(self) -> None:
        driver = _FakeDriver()
        with self.assertRaises(ValueError):
            await _index(driver).upsert_chunks(
                document_id="d1", document_name="a", chunks=["x", "y"], vectors=[[0.1] * 1024]
            )


class SearchTests(unittest.IsolatedAsyncioTestCase):
    _HIT: ClassVar[dict[str, Any]] = {
        "doc": "d1",
        "name": "a.txt",
        "idx": 3,
        "cnt": 12,
        "text": "内容",
        "score": 0.87,
    }

    async def test_dense_hit_contract(self) -> None:
        """命中 dict 是 SearchService/RRF 的契约：point_id 口径 + 类型收敛。"""

        driver = _FakeDriver(responses={"queryNodes": [dict(self._HIT, idx="7", cnt="3")]})
        hits = await _index(driver).search_by_dense(dense_vector=[0.1] * 1024, top_k=5)
        hit = hits[0]
        self.assertEqual("d1:7", hit["point_id"])  # 字符串坐标也要能拼出稳定键
        self.assertEqual(7, hit["chunk_index"])
        self.assertEqual(3, hit["chunk_count"])
        self.assertAlmostEqual(0.87, hit["score"])

    async def test_sparse_escapes_and_passes_limit(self) -> None:
        driver = _FakeDriver(responses={"fulltext": []})
        await _index(driver).search_by_sparse(query_text="苹果 维C", top_k=20)
        _, kwargs = driver.calls[0]
        self.assertEqual('"苹果" "维C"', kwargs["query"])
        self.assertEqual(20, kwargs["limit"])

    async def test_sparse_blank_query_skips_roundtrip(self) -> None:
        driver = _FakeDriver()
        hits = await _index(driver).search_by_sparse(query_text="!!! ???", top_k=5)
        self.assertEqual([], hits)
        self.assertEqual([], driver.calls)


class ReadAndDeleteTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_document_chunks_sorted_dicts(self) -> None:
        driver = _FakeDriver(
            responses={
                "c.chunk_index AS idx": [
                    {"idx": 0, "text": "零", "name": "a.txt", "cnt": 2},
                    {"idx": 1, "text": "一", "name": "a.txt", "cnt": 2},
                ]
            }
        )
        rows = await _index(driver).get_document_chunks(document_id="d1")
        self.assertEqual([0, 1], [r["chunk_index"] for r in rows])
        self.assertEqual("零", rows[0]["text"])

    async def test_get_chunk_missing_returns_none(self) -> None:
        driver = _FakeDriver()
        self.assertIsNone(await _index(driver).get_chunk(document_id="d1", chunk_index=9))

    async def test_get_chunk_found(self) -> None:
        driver = _FakeDriver(
            responses={"c.text AS text": [{"text": "那块", "name": "a.txt", "cnt": 4}]}
        )
        chunk = await _index(driver).get_chunk(document_id="d1", chunk_index=2)
        self.assertIsNotNone(chunk)
        assert chunk is not None
        self.assertEqual("那块", chunk["text"])
        self.assertEqual("a.txt", chunk["document_name"])
        self.assertEqual(2, chunk["chunk_index"])

    async def test_delete_document(self) -> None:
        driver = _FakeDriver()
        await _index(driver).delete_document(document_id="d1")
        query, kwargs = driver.calls[0]
        self.assertIn("DETACH DELETE", query)
        self.assertEqual("d1", kwargs["doc_id"])


def _neo4j_alive() -> bool:
    try:
        import asyncio

        from neo4j import AsyncGraphDatabase

        async def _ping() -> bool:
            driver = AsyncGraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password),
            )
            try:
                await driver.verify_connectivity()
            finally:
                await driver.close()
            return True

        return asyncio.run(asyncio.wait_for(_ping(), timeout=3))
    except Exception:
        return False


@pytest.mark.integration
@unittest.skipUnless(_neo4j_alive(), f"本地 Neo4j 不可用: {settings.neo4j_uri}")
class LiveIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """真 Neo4j 全链路：建索引 → 写块 → 两路查回 → 按坐标读 → 删干净。

    用生造词做 sparse 命中词，避免和任何真实语料相撞；文档 id 带 it- 前缀，
    teardown 无条件删，测完不留痕。
    """

    DOC = "it-neo4j-chunk-test"
    SPARSE_PROBE = "犞膼甲块"  # 生造词：不和真实语料相撞

    async def asyncSetUp(self) -> None:
        from neo4j import AsyncGraphDatabase

        self._driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        self._index = Neo4jChunkIndex(
            self._driver,
            embedding_dim=settings.embedding_dim,
            analyzer=settings.chunk_fulltext_analyzer,
        )
        await self._index.ensure_indexes()

    async def asyncTearDown(self) -> None:
        await self._index.delete_document(document_id=self.DOC)
        await self._driver.close()

    def _dim(self) -> list[float]:
        return [0.0] * settings.embedding_dim

    async def test_round_trip_dense_sparse_and_reads(self) -> None:
        v0, v1 = self._dim(), self._dim()
        v0[0] = 1.0
        v1[1] = 1.0
        count = await self._index.upsert_chunks(
            document_id=self.DOC,
            document_name="IT文档.txt",
            chunks=[f"{self.SPARSE_PROBE} 的内容", "第二块无关"],
            vectors=[v0, v1],
        )
        self.assertEqual(2, count)

        dense = await self._index.search_by_dense(dense_vector=v0, top_k=5)
        hits = [h for h in dense if h["document_id"] == self.DOC]
        self.assertEqual(0, hits[0]["chunk_index"])
        self.assertEqual(f"{self.DOC}:0", hits[0]["point_id"])
        self.assertAlmostEqual(1.0, hits[0]["score"], places=3)

        sparse = await self._index.search_by_sparse(query_text=self.SPARSE_PROBE, top_k=5)
        self.assertIn(self.DOC, {h["document_id"] for h in sparse})

        rows = await self._index.get_document_chunks(document_id=self.DOC)
        self.assertEqual([0, 1], [r["chunk_index"] for r in rows])
        self.assertEqual(f"{self.SPARSE_PROBE} 的内容", rows[0]["text"])

        chunk = await self._index.get_chunk(document_id=self.DOC, chunk_index=1)
        assert chunk is not None
        self.assertEqual("第二块无关", chunk["text"])
        self.assertEqual("IT文档.txt", chunk["document_name"])

        await self._index.delete_document(document_id=self.DOC)
        self.assertIsNone(
            await self._index.get_chunk(document_id=self.DOC, chunk_index=0)
        )

    async def test_ensure_rejects_foreign_dim_on_live_index(self) -> None:
        """索引已按 embedding_dim 建好，拿不同维度的实例启动必须炸在组装期。"""

        wrong = Neo4jChunkIndex(
            self._driver,
            embedding_dim=settings.embedding_dim + 1,
            analyzer=settings.chunk_fulltext_analyzer,
        )
        with self.assertRaises(RuntimeError):
            await wrong.ensure_indexes()


if __name__ == "__main__":
    unittest.main()
