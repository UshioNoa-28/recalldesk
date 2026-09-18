"""GraphRecallChannel：种子选择优先级与扩展（假 store）。"""

from __future__ import annotations

import unittest
from typing import Any

from app.application.services.graph.graph_channel import GraphRecallChannel


class FakeStore:
    def __init__(self, *, by_names: list[str] | None = None, by_text: list[str] | None = None,
                 by_vector: list[str] | None = None, expand: list[dict] | None = None,
                 error: Exception | None = None) -> None:
        self.by_names = by_names or []
        self.by_text = by_text or []
        self.by_vector = by_vector or []
        self.expand = expand or []
        self.error = error
        self.calls: list[Any] = []

    async def link_by_names(self, names, *, limit):
        self.calls.append(("names", names, limit))
        if self.error:
            raise self.error
        return self.by_names

    async def link_by_text(self, query, *, limit):
        self.calls.append(("text", query, limit))
        return self.by_text

    async def link_by_vector(self, vector, *, limit, min_score):
        self.calls.append(("vector", limit, min_score))
        return self.by_vector

    async def expand_from(self, seeds, *, hops, limit):
        self.calls.append(("expand", seeds, hops, limit))
        if not seeds:
            return []  # 与真 store 同款守门：channel 不重复检查
        return self.expand


class GraphRecallChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_entities_hint_takes_priority_and_expands_seeds(self) -> None:
        store = FakeStore(by_names=["苹果"], expand=[{"point_id": "d1:3"}])
        channel = GraphRecallChannel(store, hops=2, candidates=20)

        hits = await channel.recall("苹果 补铁", entities=["苹果"])

        self.assertEqual([{"point_id": "d1:3"}], hits)
        self.assertIn(("names", ["苹果"], 5), store.calls)
        self.assertIn(("expand", ["苹果"], 2, 20), store.calls)

    async def test_falls_back_to_text_link_without_hints(self) -> None:
        store = FakeStore(by_text=["铁"])
        channel = GraphRecallChannel(store)

        await channel.recall("有点缺铁怎么办")

        self.assertIn(("text", "有点缺铁怎么办", 5), store.calls)
        self.assertTrue(any(c[0] == "expand" for c in store.calls))

    async def test_no_seeds_short_circuits_at_the_store(self) -> None:
        """channel 不复检空种子——短路责任在 expand_from（一次调用，两处一致）。"""

        store = FakeStore()
        channel = GraphRecallChannel(store)

        self.assertEqual([], await channel.recall("无关问题", entities=["不存在的东西"]))
        self.assertEqual([("expand", [], 2, 20)],
                         [c for c in store.calls if c[0] == "expand"])

    async def test_vector_link_is_the_safety_net(self) -> None:
        store = FakeStore(by_vector=["铁"], expand=[{"point_id": "d1:1"}])
        channel = GraphRecallChannel(store, link_min_score=0.4)

        hits = await channel.recall("最近有点缺铁", query_vector=[0.1, 0.2])

        self.assertTrue(any(c[0] == "vector" and c[2] == 0.4 for c in store.calls))
        self.assertIn(("expand", ["铁"], 2, 20), store.calls)
        self.assertEqual([{"point_id": "d1:1"}], hits)

    async def test_three_sources_merge_dedupe_in_priority_order(self) -> None:
        store = FakeStore(by_names=["a"], by_text=["a", "b"], by_vector=["b", "c"])

        await GraphRecallChannel(store).recall(
            "q", entities=["A"], query_vector=[0.1]
        )

        self.assertIn(("expand", ["a", "b", "c"], 2, 20), store.calls)

    async def test_store_error_propagates_for_search_to_degrade(self) -> None:
        # 频道自己不吞异常：降级决策归 SearchService（单一职责）
        channel = GraphRecallChannel(FakeStore(error=ConnectionError("neo4j down")))
        with self.assertRaises(ConnectionError):
            await channel.recall("q", entities=["x"])


if __name__ == "__main__":
    unittest.main()
