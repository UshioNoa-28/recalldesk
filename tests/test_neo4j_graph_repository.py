"""Neo4jGraphRepository 单测（fake driver）：索引/整篇替换/链接/扩展的语句与映射。"""

from __future__ import annotations

import unittest
from typing import Any

from app.domain.graph import GraphEntity, GraphTriple
from app.infrastructure.neo4j.graph_repository import Neo4jGraphRepository


class _FakeResult:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.records = records


class _FakeDriver:
    def __init__(self, responses: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.responses = responses or {}

    async def execute_query(self, query_: str, **kwargs: Any) -> _FakeResult:
        self.calls.append((query_, kwargs))
        for key, records in self.responses.items():
            if key in query_:
                return _FakeResult([dict(r) for r in records])
        return _FakeResult([])


def _store(driver: _FakeDriver, **kw: Any) -> Neo4jGraphRepository:
    return Neo4jGraphRepository(driver, embedding_dim=kw.pop("dim", 1024), **kw)


class EnsureIndexesTests(unittest.IsolatedAsyncioTestCase):
    async def test_creates_constraint_fulltext_and_vector(self) -> None:
        driver = _FakeDriver()
        await _store(driver).ensure_indexes()
        joined = "\n".join(q for q, _ in driver.calls)
        self.assertIn("CREATE CONSTRAINT entity_name_norm", joined)
        self.assertIn("CREATE FULLTEXT INDEX entity_text", joined)
        self.assertIn("fulltext.analyzer", joined)
        self.assertIn("CREATE VECTOR INDEX entity_embedding", joined)

    async def test_foreign_dim_vector_index_fails_fast(self) -> None:
        driver = _FakeDriver(
            responses={"SHOW VECTOR INDEXES": [{"cfg": {"vector.dimensions": 512}}]}
        )
        with self.assertRaises(RuntimeError):
            await _store(driver).ensure_indexes()


class UpsertTests(unittest.IsolatedAsyncioTestCase):
    async def test_replaces_document_graph_in_one_roundtrip(self) -> None:
        driver = _FakeDriver(
            # 复活守卫先数本篇 chunk：给个非零数放行（计数走 Python 侧；清扫独立成第二发查询）
            responses={"count(c) AS n": [{"n": 27}]}
        )
        count = await _store(driver).upsert_document_graph(
            document_id="d1",
            entities=[GraphEntity(name_norm="苹果", name="苹果")],
            triples=[GraphTriple(src_norm="苹果", dst_norm="维c", relation="富含", chunk_index=0)],
        )
        self.assertEqual(1, count)  # 计数 = 实体数（Python 侧）
        self.assertEqual(3, len(driver.calls))  # 守卫计数 + 主写入 + 孤儿清扫
        self.assertIn("count(c) AS n", driver.calls[0][0])  # 复活守卫永远先跑
        query, kwargs = driver.calls[1]
        # 证据清账按本篇前缀剔（不整边删：多出处共存），掏空的才删；写子句之间有 WITH 屏障
        self.assertIn("NOT x STARTS WITH $prefix", query)
        self.assertIn("COALESCE(size(r.evidence), 0) = 0 DELETE r", query)
        self.assertIn("MERGE (e:Entity {name_norm: ent.name_norm})", query)
        self.assertIn("REDUCE(acc = []", query)  # 别名并集 + 证据去重共用 REDUCE 手法
        self.assertIn("MERGE (a)-[r:REL {type: t.relation}]->(b)", query)
        self.assertNotIn("SUPPORTS]->(e)", query)  # 实体级支撑已退役（只剩过渡清理子句）
        self.assertEqual("苹果", kwargs["entities"][0]["name_norm"])  # asdict 后仍是 dict 参数
        self.assertEqual("d1:", kwargs["prefix"])
        self.assertEqual("d1:0", kwargs["triples"][0]["evidence"])  # point_id 口径
        self.assertIn("NOT (e)--()", driver.calls[2][0])  # 清扫已独立
        self.assertEqual("d1", kwargs["doc"])
        self.assertEqual(1, len(kwargs["triples"]))

    async def test_resurrection_guard_aborts_when_no_chunks(self) -> None:
        """删除超车慢抽取的验尸课：本篇 chunk 已归零时，迟到的回写整篇作废。"""

        driver = _FakeDriver(responses={"count(c) AS n": [{"n": 0}]})

        count = await _store(driver).upsert_document_graph(
            document_id="ghost",
            entities=[GraphEntity(name_norm="苹果", name="苹果")],
            triples=[],
        )

        self.assertEqual(0, count)
        self.assertEqual(1, len(driver.calls))  # 只发了守卫，主写入/清扫都没跑
        self.assertIn("count(c) AS n", driver.calls[0][0])


class DeleteTests(unittest.IsolatedAsyncioTestCase):
    async def test_delete_document_graph(self) -> None:
        driver = _FakeDriver()
        await _store(driver).delete_document_graph("d1")
        query, kwargs = driver.calls[0]
        # 同款证据减法：剔本篇前缀 → 掏空的删 → 遗留 SUPPORTS 一并清
        self.assertIn("NOT x STARTS WITH $prefix", query)
        self.assertIn("COALESCE(size(r.evidence), 0) = 0 DELETE r", query)
        self.assertIn("[s:SUPPORTS]->() DELETE s", query)
        self.assertEqual("d1:", kwargs["prefix"])
        self.assertIn("NOT (e)--()", driver.calls[1][0])  # 删完必扫孤儿


class LinkAndExpandTests(unittest.IsolatedAsyncioTestCase):
    async def test_link_by_names_normalizes_and_blank_short_circuits(self) -> None:
        driver = _FakeDriver(responses={"collect(DISTINCT e.name_norm)": [{"norms": ["苹果"]}]})
        norms = await _store(driver).link_by_names([" 苹果 ", ""], limit=5)
        self.assertEqual(["苹果"], norms)
        self.assertEqual(["苹果"], driver.calls[0][1]["names"])
        self.assertEqual([], await _store(_FakeDriver()).link_by_names([], limit=5))
        self.assertEqual([], await _store(_FakeDriver()).link_by_names(["   "], limit=5))

    async def test_link_by_text_escapes_and_maps(self) -> None:
        driver = _FakeDriver(
            responses={"fulltext.queryNodes": [{"norm": "铁"}, {"norm": None}]}
        )
        norms = await _store(driver).link_by_text("缺铁 !!!", limit=3)
        self.assertEqual(["铁"], norms)
        self.assertEqual('"缺铁"', driver.calls[0][1]["query"])
        self.assertEqual([], await _store(_FakeDriver()).link_by_text("!!! ???", limit=3))

    async def test_link_by_vector_threshold_and_short_circuit(self) -> None:
        driver = _FakeDriver(
            responses={"vector.queryNodes": [{"norm": "苹果", "score": 0.9}]}
        )
        norms = await _store(driver).link_by_vector([0.1] * 4, limit=5, min_score=0.65)
        self.assertEqual(["苹果"], norms)
        _, kwargs = driver.calls[0]
        self.assertEqual(0.65, kwargs["min_score"])
        # 阈值 <=0 = 关闭该路：不查库
        quiet = _FakeDriver()
        self.assertEqual([], await _store(quiet).link_by_vector([0.1], limit=5, min_score=0.0))
        self.assertEqual([], quiet.calls)

    async def test_expand_maps_rows_to_channel_hits(self) -> None:
        driver = _FakeDriver(
            responses={
                "c.document_name AS name": [
                    {"doc": "d1", "idx": 0, "text": "T0", "name": "a.txt", "cnt": 2},
                    {"doc": "d1", "idx": 1, "text": "T1", "name": "a.txt", "cnt": 2},
                ]
            }
        )
        hits = await _store(driver).expand_from(["苹果"], hops=1, limit=20)
        self.assertEqual(2, len(hits))
        self.assertEqual("d1:0", hits[0]["point_id"])
        self.assertEqual("T1", hits[1]["text"])
        # 证据取自路径边：SUPPORTS 反查退役，坐标 join Chunk 兜悬空
        query = driver.calls[0][0]
        self.assertIn("relationships(path)", query)
        self.assertIn("MATCH (c:Chunk {doc_id: split(coord, ':')[0]", query)
        # 通道内名次分：严格递减即可（RRF 只看组内序）
        self.assertGreater(hits[0]["score"], hits[1]["score"])
        self.assertEqual([], await _store(_FakeDriver()).expand_from([], hops=1, limit=5))

    async def test_expand_clamps_hops(self) -> None:
        driver = _FakeDriver()
        await _store(driver).expand_from(["x"], hops=99, limit=20)
        self.assertIn("*1..3", driver.calls[0][0])  # 钉死在 3，参数不直进 Cypher


class ExplorerPrimitivesTests(unittest.IsolatedAsyncioTestCase):
    async def test_neighborhood_two_roundtrips_nodes_then_edges(self) -> None:
        driver = _FakeDriver(
            responses={
                "AS path_evidence": [
                    {"norm": "咖啡", "name": "咖啡", "type": "饮品",
                     "hops": 0, "path_evidence": 5},
                    {"norm": "咖啡因", "name": "咖啡因", "type": "物质",
                     "hops": 1, "path_evidence": 2},
                ],
                "ORDER BY src, dst, type": [
                    {"src": "咖啡", "dst": "咖啡因", "type": "含有", "evidence": ["d1:0", "d2:3"]},
                    {"src": "咖啡", "dst": "咖啡因", "type": "提神", "evidence": None},
                ],
            }
        )
        sub = await _store(driver).neighborhood(["咖啡"], hops=2, limit=60)
        self.assertEqual(2, len(driver.calls))  # 圈节点 + 收边，两发只读
        self.assertEqual(2, len(sub["nodes"]))
        self.assertEqual(0, sub["nodes"][0]["hops"])  # 种子在 0 跳
        self.assertEqual(5, sub["nodes"][0]["path_evidence"])  # 键随语义改名：通往中心的路径证据
        self.assertEqual(2, len(sub["edges"]))
        self.assertEqual(["d1:0", "d2:3"], sub["edges"][0]["evidence"])
        self.assertEqual([], sub["edges"][1]["evidence"])  # null 证据归一成空表
        node_query = driver.calls[0][0]
        self.assertIn("*0..2", node_query)  # 种子自包含靠 0 跳变长
        # 截断权重=最强制通路径的证据数（reduce 沿 paths 收），不是全局邻边总和
        self.assertIn("max(size(evidence)) AS path_evidence", node_query)
        self.assertNotIn("(n)-[r:REL]-()", node_query)
        self.assertIn("ORDER BY hops ASC, path_evidence DESC", node_query)
        self.assertIn("WHERE b.name_norm IN $norms", driver.calls[1][0])  # 边两端都在圈内

    async def test_neighborhood_empty_when_seed_unmatched(self) -> None:
        driver = _FakeDriver()  # 第一发返回空 records → 不必发第二发
        sub = await _store(driver).neighborhood(["查无此人"], hops=1, limit=60)
        self.assertEqual({"nodes": [], "edges": []}, sub)
        self.assertEqual(1, len(driver.calls))
        empty = await _store(_FakeDriver()).neighborhood([], hops=1, limit=5)
        self.assertEqual({"nodes": [], "edges": []}, empty)

    async def test_search_entities_prefix_priority_query(self) -> None:
        driver = _FakeDriver(
            responses={
                "ORDER BY priority ASC": [
                    {"norm": "咖啡", "name": "咖啡", "type": "饮品", "description": None,
                     "degree": 3, "evidence_count": 5},
                    {"norm": "咖啡因", "name": "咖啡因", "type": "物质", "description": None,
                     "degree": 5, "evidence_count": 8},
                ]
            }
        )
        results = await _store(driver).search_entities("咖啡", limit=5)
        self.assertEqual(2, len(results))
        self.assertEqual("咖啡", results[0]["name"])
        query_text = driver.calls[0][0]
        self.assertIn("CONTAINS $q", query_text)
        self.assertIn("STARTS WITH $q", query_text)
        self.assertIn("ORDER BY priority ASC", query_text)


if __name__ == "__main__":
    unittest.main()
