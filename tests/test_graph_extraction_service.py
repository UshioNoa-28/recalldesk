"""GraphExtractionService：归并、越界三元组丢弃、embedding 批量。"""

from __future__ import annotations

import unittest
from typing import Any

from app.application.services.graph.graph_extraction_service import (
    GraphChunkExtraction,
    GraphEntityOut,
    GraphExtractionService,
    GraphTripleOut,
    normalize_name,
)


class FakeLlm:
    def __init__(self, outputs: dict[int, GraphChunkExtraction]) -> None:
        self._outputs = outputs
        self.prompts: list[str] = []

    async def generate_structured(self, prompt: str, schema: Any) -> Any:
        self.prompts.append(prompt)
        for index, out in self._outputs.items():
            if f"切片 #{index}" in prompt:
                return out
        raise AssertionError("no output for prompt")


class FakeEmbedding:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(t)) % 1, 0.5] for t in texts]


def _entity(name: str, **kw: Any) -> GraphEntityOut:
    return GraphEntityOut(name=name, **kw)


def _extraction(
    entities: list[GraphEntityOut],
    triples: list[GraphTripleOut] | None = None,
) -> GraphChunkExtraction:
    return GraphChunkExtraction(entities=entities, triples=triples or [])


class GraphExtractionServiceTests(unittest.IsolatedAsyncioTestCase):
    async def _build(
        self, outputs: dict[int, GraphChunkExtraction]
    ) -> tuple[GraphExtractionService, FakeLlm]:
        llm = FakeLlm(outputs)
        service = GraphExtractionService(
            llm_client=llm, embedding_client=FakeEmbedding(), concurrency=2
        )
        return service, llm

    async def test_merges_entities_across_chunks_and_embeds_once(self) -> None:
        service, _ = await self._build({
            0: _extraction([_entity("苹果", type="水果"), _entity("维生素C", type="物质")],
                           [GraphTripleOut(src="苹果", dst="维生素C", relation="富含"),
                            GraphTripleOut(src="苹果", dst="不存在", relation="编造")]),
            1: _extraction([_entity("维生素C", type="物质", aliases=["维C"])]),
        })

        contribution = await service.build("营养指南.txt", [
            {"chunk_index": 0, "text": "苹果富含维C"},
            {"chunk_index": 1, "text": "维C促进吸收"},
        ])

        by_norm = {e.name_norm: e for e in contribution.entities}
        self.assertEqual({"苹果", "维生素c"}, set(by_norm))
        self.assertTrue(by_norm["苹果"].embedding)  # 全部实体过了一遍 embedding
        # 越界三元组（端点 "不存在" 未声明）被丢弃，合法的一条保留
        self.assertEqual(1, len(contribution.triples))
        triple = contribution.triples[0]
        self.assertEqual("苹果", triple.src_norm)
        self.assertEqual("维生素c", triple.dst_norm)

    async def test_alias_endpoint_resolves_to_declared_entity(self) -> None:
        service, _ = await self._build({
            0: _extraction([_entity("维生素C", aliases=["维C"]), _entity("铁")],
                           [GraphTripleOut(src="维C", dst="铁", relation="促进吸收")]),
        })
        contribution = await service.build("d.txt", [{"chunk_index": 0, "text": "x"}])
        self.assertEqual("维生素c", contribution.triples[0].src_norm)

    async def test_self_loop_and_blank_relation_dropped(self) -> None:
        service, _ = await self._build({
            0: _extraction([_entity("苹果"), _entity("水果")],
                           [GraphTripleOut(src="苹果", dst="苹果", relation="是"),
                            GraphTripleOut(src="水果", dst="苹果", relation="  ")]),
        })
        contribution = await service.build("d.txt", [{"chunk_index": 0, "text": "x"}])
        self.assertEqual([], contribution.triples)

    async def test_normalize_name(self) -> None:
        self.assertEqual("apple inc", normalize_name("  Apple   Inc "))


if __name__ == "__main__":
    unittest.main()
