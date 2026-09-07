"""IndexingService 单元测试（假仓储/假 embedding/假 splitter，离线运行）。"""

from __future__ import annotations

import unittest
from unittest import IsolatedAsyncioTestCase as TestCase

from app.application.services.indexing_service import IndexingService


class _FakeRepository:
    def __init__(self) -> None:
        self.upserts: list[dict] = []

    async def upsert_chunks(self, **kwargs) -> int:
        self.upserts.append(kwargs)
        return len(kwargs["chunks"])


class _FakeEmbeddingClient:
    def __init__(self, dim: int = 4) -> None:
        self.dim = dim
        self.batches: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.batches.append(texts)
        return [[float(len(t))] * self.dim for t in texts]

    async def embed_one(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]


class _FakeSplitService:
    """按句切分的假分块服务（离线、确定性），顺带记下收到的文档名。"""

    def __init__(self) -> None:
        self.names: list[str] = []

    def split(self, name: str, text: str) -> list[str]:
        import re

        self.names.append(name)
        return [p for p in re.split(r"(?<=[。！？])\s*", text) if p.strip()]


class IndexingServiceTests(TestCase):
    async def test_ingest_splits_embeds_and_upserts(self) -> None:
        repository = _FakeRepository()
        split_service = _FakeSplitService()
        service = IndexingService(
            repository=repository,
            embedding_client=_FakeEmbeddingClient(),
            split_service=split_service,
        )
        text = "苹果发布新款手机，性能强劲。香蕉富含维生素钾。"

        written = await service.ingest("doc-9", "水果.txt", text)

        self.assertEqual(2, written)
        # 选哪种切法由文档名决定，所以名字要一路传到分块这一步
        self.assertEqual(["水果.txt"], split_service.names)
        self.assertEqual(1, len(repository.upserts))
        upsert = repository.upserts[0]
        self.assertEqual("doc-9", upsert["document_id"])
        self.assertEqual("水果.txt", upsert["document_name"])
        self.assertEqual(2, len(upsert["chunks"]))
        # 假 embedding 按文本长度填充：14 字 / 9 字
        self.assertEqual([14.0, 9.0], [v[0] for v in upsert["vectors"]])
        self.assertEqual(upsert["chunks"], service._embedding_client.batches[0])

    async def test_ingest_empty_document_raises(self) -> None:
        service = IndexingService(
            repository=_FakeRepository(),
            embedding_client=_FakeEmbeddingClient(),
            split_service=_FakeSplitService(),
        )

        with self.assertRaises(ValueError):
            await service.ingest("doc-9", "empty.txt", "   ")


if __name__ == "__main__":
    unittest.main()
