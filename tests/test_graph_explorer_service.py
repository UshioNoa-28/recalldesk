"""GraphExplorerService 单测：实体名称搜索补全与卡片映射。"""

from __future__ import annotations

import unittest
from typing import Any
from unittest import IsolatedAsyncioTestCase

from app.application.services.graph.graph_channel import GraphRecallChannel
from app.application.services.graph.graph_explorer_service import GraphExplorerService


class FakeStore:
    def __init__(self, *, cards: dict[str, dict[str, Any]] | None = None) -> None:
        self.cards = cards or {}
        self.search_calls: list[str] = []
        self.neighborhood_calls: list[dict] = []

    async def search_entities(self, query: str, *, limit: int = 8) -> list[dict]:
        self.search_calls.append(query)
        matched = [
            c for c in self.cards.values()
            if query in c["name"] or query in c["name_norm"]
        ]
        return matched[:limit]

    async def neighborhood(self, seeds: list[str], *, hops: int, limit: int) -> dict:
        self.neighborhood_calls.append({"seeds": seeds, "hops": hops, "limit": limit})
        return {"nodes": [{"name_norm": "咖啡因", "hops": 0}], "edges": []}


def _service(store: FakeStore) -> GraphExplorerService:
    channel = GraphRecallChannel(store, link_min_score=0.7)  # type: ignore[arg-type]
    return GraphExplorerService(store=store, channel=channel)  # type: ignore[arg-type]


_CARDS = {
    n: {
        "name_norm": n,
        "name": n,
        "type": "物质",
        "description": "",
        "degree": 1,
        "evidence_count": 1,
    }
    for n in ("咖啡", "咖啡因", "咖啡豆", "茶")
}


class SearchEntitiesTests(IsolatedAsyncioTestCase):
    async def test_search_prefix_entities(self) -> None:
        store = FakeStore(cards=_CARDS)
        results = await _service(store).search_entities("咖啡")
        self.assertEqual(["咖啡", "咖啡因", "咖啡豆"], [r["name_norm"] for r in results])
        self.assertEqual(["咖啡"], store.search_calls)

    async def test_no_cards_matched_returns_empty(self) -> None:
        store = FakeStore(cards={})
        self.assertEqual([], await _service(store).search_entities("未知"))


class NeighborhoodTests(IsolatedAsyncioTestCase):
    async def test_passthrough_single_seed(self) -> None:
        store = FakeStore()
        sub = await _service(store).neighborhood("咖啡因", hops=2, limit=60)
        self.assertEqual([{"seeds": ["咖啡因"], "hops": 2, "limit": 60}], store.neighborhood_calls)
        self.assertEqual(1, len(sub["nodes"]))


if __name__ == "__main__":
    unittest.main()
