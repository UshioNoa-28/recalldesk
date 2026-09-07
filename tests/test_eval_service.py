"""EvalService 用例测试（全 fake，不连 PG / Qdrant）：建集、加题、列表 / 详情 / 删除。"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

from app.application.services.eval_service import DEFAULT_TESTSET_NAME, EvalService
from app.domain.documents import Document, DocumentStatus
from app.domain.eval import ChunkRef, EvalTestSet, EvalTestSetItem, TestSetStatus

CREATED_AT = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def _refs(*pairs: tuple[str, int]) -> list[ChunkRef]:
    """测试里少写点样板：(document_id, chunk_index) -> ChunkRef。"""

    return [
        ChunkRef(document_id=document_id, chunk_index=index)
        for document_id, index in pairs
    ]


def _document(document_id: str = "doc-1", name: str = "营养指南.txt") -> Document:
    return Document(
        id=document_id,
        name=name,
        storage_key=f"{document_id}.txt",
        size_bytes=10,
        checksum_sha256="sha",
        media_type="text/plain",
        status=DocumentStatus.SUCCESS,
    )


def _chunk(chunk_index: int) -> dict:
    """向量库里已索引的一个分块：只有 chunk_index 是校验要看的。

    刻意不给 text —— 服务读它就说明有人在往 PG 里抄原文，测试会因此炸。
    """

    return {"chunk_index": chunk_index}


class FakeEvalRepository:
    """按坐标存题目，item id 留到 list 时才生成（真仓储靠 flush，同理）。"""

    def __init__(self) -> None:
        self.testsets: dict[str, EvalTestSet] = {}
        self.coords: dict[str, list[ChunkRef]] = {}
        self.reopened: list[str] = []

    async def create_testset(self, *, testset_id: str, name: str) -> None:
        self.testsets[testset_id] = EvalTestSet(
            id=testset_id,
            name=name,
            status=TestSetStatus.GENERATING,
            progress_done=0,
            progress_total=0,
            error_message=None,
            created_at=CREATED_AT,
        )
        self.coords[testset_id] = []

    async def add_testset_items(self, testset_id: str, refs: list[ChunkRef]) -> None:
        self.coords.setdefault(testset_id, []).extend(refs)

    async def reopen_testset(self, testset_id: str) -> None:
        self.reopened.append(testset_id)
        testset = self.testsets[testset_id]
        testset.status = TestSetStatus.GENERATING
        testset.error_message = None

    async def list_testset_items(self, testset_id: str) -> list[EvalTestSetItem]:
        return [
            EvalTestSetItem(
                id=f"{testset_id}-item-{index}",
                answer_document_id=ref.document_id,
                answer_chunk_index=ref.chunk_index,
            )
            for index, ref in enumerate(self.coords.get(testset_id, []))
        ]

    async def get_testset(self, testset_id: str) -> EvalTestSet | None:
        testset = self.testsets.get(testset_id)
        if testset is None:
            return None
        testset.progress_total = len(self.coords.get(testset_id, []))
        return testset

    async def list_testsets(self) -> list[EvalTestSet]:
        for testset_id in self.testsets:
            await self.get_testset(testset_id)
        return list(self.testsets.values())

    async def delete_testset(self, testset_id: str) -> None:
        self.testsets.pop(testset_id, None)
        self.coords.pop(testset_id, None)


class FakeEvalTaskRepository:
    def __init__(self) -> None:
        self.added: list[tuple[str, str]] = []

    async def add(self, *, testset_id: str, item_id: str) -> None:
        self.added.append((testset_id, item_id))


class FakeDocumentRepository:
    def __init__(self, documents: dict[str, Document]) -> None:
        self._documents = documents

    async def get(self, document_id: str) -> Document | None:
        return self._documents.get(document_id)


class FakeVectorRepository:
    def __init__(self, chunks: dict[str, list[dict]]) -> None:
        self._chunks = chunks
        self.scrolled: list[str] = []

    async def get_document_chunks(self, *, document_id: str) -> list[dict]:
        self.scrolled.append(document_id)
        return self._chunks.get(document_id, [])


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


def _make(
    *,
    documents: dict[str, Document] | None = None,
    chunks: dict[str, list[dict]] | None = None,
) -> SimpleNamespace:
    evals = FakeEvalRepository()
    tasks = FakeEvalTaskRepository()
    uow = FakeUnitOfWork()
    vectors = FakeVectorRepository(
        {"doc-1": [_chunk(0), _chunk(1)]} if chunks is None else chunks
    )
    service = EvalService(
        eval_repository=evals,
        eval_task_repository=tasks,
        documents=FakeDocumentRepository(
            {"doc-1": _document()} if documents is None else documents
        ),
        vector_repository=vectors,
        unit_of_work=uow,
    )
    return SimpleNamespace(service=service, evals=evals, tasks=tasks, uow=uow, vectors=vectors)


async def _testset_with_items(*pairs: tuple[str, int]) -> SimpleNamespace:
    """建一个集并加好题：读/删用例的前置状态。"""

    ctx = _make()
    await ctx.service.create_testset(name="水果题集")
    testset_id = next(iter(ctx.evals.testsets))
    await ctx.service.add_items(testset_id, _refs(*pairs))
    return ctx


class EvalServiceCreateTestSetTests(IsolatedAsyncioTestCase):
    async def test_creates_an_empty_testset_in_one_transaction(self) -> None:
        ctx = _make()

        result = await ctx.service.create_testset(name="水果题集")

        testset_id = result["id"]
        self.assertEqual(1, ctx.uow.commits)
        self.assertEqual([testset_id], list(ctx.evals.testsets))
        self.assertEqual("水果题集", ctx.evals.testsets[testset_id].name)
        self.assertEqual([], ctx.tasks.added)
        self.assertEqual(0, result["progress_total"])
        self.assertEqual([], result["items"])

    async def test_blank_name_falls_back_to_default(self) -> None:
        ctx = _make()

        result = await ctx.service.create_testset(name="   ")

        testset_id = result["id"]
        self.assertEqual(DEFAULT_TESTSET_NAME, ctx.evals.testsets[testset_id].name)
        self.assertEqual(DEFAULT_TESTSET_NAME, result["name"])


class EvalServiceAddItemsTests(IsolatedAsyncioTestCase):
    async def test_writes_coordinates_and_one_task_per_item_in_one_transaction(self) -> None:
        ctx = _make()
        await ctx.service.create_testset(name="水果题集")
        testset_id = next(iter(ctx.evals.testsets))

        result = await ctx.service.add_items(testset_id, _refs(("doc-1", 0), ("doc-1", 1)))

        self.assertEqual(2, ctx.uow.commits)  # 建集一次、加题一次
        self.assertEqual(
            _refs(("doc-1", 0), ("doc-1", 1)), ctx.evals.coords[testset_id]
        )
        self.assertEqual(
            [(testset_id, f"{testset_id}-item-{i}") for i in (0, 1)], ctx.tasks.added
        )
        self.assertEqual(
            {
                "id": testset_id,
                "name": "水果题集",
                "status": "generating",
                "progress_done": 0,
                "progress_total": 2,
                "error_message": None,
                "created_at": CREATED_AT.isoformat(),
                "items": [
                    {
                        "id": f"{testset_id}-item-{i}",
                        "query": None,
                        "status": "pending",
                        "error_message": None,
                        "answer_document_id": "doc-1",
                        "answer_chunk_index": i,
                    }
                    for i in (0, 1)
                ],
            },
            result,
        )

    async def test_reopens_the_testset_so_progress_counts_the_new_items(self) -> None:
        """ready 的集加了新题必须退回 generating，否则列表上永远显示 ready。"""

        ctx = await _testset_with_items(("doc-1", 0))
        testset_id = next(iter(ctx.evals.testsets))
        ctx.evals.testsets[testset_id].status = TestSetStatus.READY
        ctx.evals.testsets[testset_id].error_message = "1 项生成失败"
        ctx.evals.reopened.clear()

        await ctx.service.add_items(testset_id, _refs(("doc-1", 1)))

        self.assertEqual([testset_id], ctx.evals.reopened)
        self.assertEqual("generating", ctx.evals.testsets[testset_id].status.value)
        self.assertIsNone(ctx.evals.testsets[testset_id].error_message)

    async def test_dedupes_the_batch_and_skips_coordinates_already_in_the_set(self) -> None:
        """(testset_id, document_id, chunk_index) 上有唯一约束，同块两题必撞。"""

        ctx = await _testset_with_items(("doc-1", 0))
        testset_id = next(iter(ctx.evals.testsets))
        ctx.tasks.added.clear()

        result = await ctx.service.add_items(
            testset_id, _refs(("doc-1", 1), ("doc-1", 1), ("doc-1", 0))
        )

        self.assertEqual(_refs(("doc-1", 0), ("doc-1", 1)), ctx.evals.coords[testset_id])
        self.assertEqual([(testset_id, f"{testset_id}-item-1")], ctx.tasks.added)
        self.assertEqual(2, result["progress_total"])

    async def test_adding_only_known_coordinates_writes_nothing_and_keeps_status(self) -> None:
        """一道新题都没有：不能 reopen，没有任务就没人 finalize，集会卡在 generating。"""

        ctx = await _testset_with_items(("doc-1", 0))
        testset_id = next(iter(ctx.evals.testsets))
        ctx.evals.testsets[testset_id].status = TestSetStatus.READY
        commits_before = ctx.uow.commits
        ctx.tasks.added.clear()
        ctx.evals.reopened.clear()

        result = await ctx.service.add_items(testset_id, _refs(("doc-1", 0)))

        self.assertEqual([], ctx.evals.reopened)
        self.assertEqual([], ctx.tasks.added)
        self.assertEqual(commits_before, ctx.uow.commits)
        self.assertEqual("ready", result["status"])

    async def test_validates_coordinates_of_two_documents_with_one_scroll_each(self) -> None:
        ctx = _make(
            documents={"doc-1": _document(), "doc-2": _document("doc-2", "其他.txt")},
            chunks={"doc-1": [_chunk(0), _chunk(1)], "doc-2": [_chunk(0)]},
        )
        await ctx.service.create_testset(name="两文档")
        testset_id = next(iter(ctx.evals.testsets))

        await ctx.service.add_items(
            testset_id, _refs(("doc-1", 0), ("doc-1", 1), ("doc-2", 0))
        )

        self.assertEqual(["doc-1", "doc-2"], ctx.vectors.scrolled)

    async def test_unknown_testset_raises_keyerror_without_committing(self) -> None:
        ctx = _make()

        with self.assertRaises(KeyError):
            await ctx.service.add_items("ghost", _refs(("doc-1", 0)))

        self.assertEqual(0, ctx.uow.commits)
        self.assertEqual([], ctx.tasks.added)

    async def test_missing_document_raises_value_error_without_committing(self) -> None:
        ctx = _make(documents={})
        await ctx.service.create_testset(name="x")
        testset_id = next(iter(ctx.evals.testsets))
        commits_before = ctx.uow.commits

        with self.assertRaises(ValueError) as exc:
            await ctx.service.add_items(testset_id, _refs(("ghost", 0)))

        self.assertIn("不存在", str(exc.exception))
        self.assertEqual(commits_before, ctx.uow.commits)
        self.assertEqual([], ctx.tasks.added)

    async def test_unknown_chunk_index_raises_value_error_without_committing(self) -> None:
        ctx = _make()
        await ctx.service.create_testset(name="x")
        testset_id = next(iter(ctx.evals.testsets))
        commits_before = ctx.uow.commits

        with self.assertRaises(ValueError) as exc:
            await ctx.service.add_items(testset_id, _refs(("doc-1", 0), ("doc-1", 9)))

        self.assertIn("切片 #9", str(exc.exception))
        self.assertEqual(commits_before, ctx.uow.commits)
        self.assertEqual([], ctx.tasks.added)
        self.assertNotIn(testset_id, ctx.evals.reopened)


class EvalServiceReadDeleteTests(IsolatedAsyncioTestCase):
    async def test_list_returns_testsets_without_items(self) -> None:
        ctx = await _testset_with_items(("doc-1", 0))

        result = await ctx.service.list_testsets()

        self.assertEqual(["水果题集"], [ts["name"] for ts in result["testsets"]])
        self.assertEqual(1, result["testsets"][0]["progress_total"])
        self.assertNotIn("items", result["testsets"][0])

    async def test_get_unknown_testset_raises_keyerror(self) -> None:
        ctx = _make()

        with self.assertRaises(KeyError):
            await ctx.service.get_testset("ghost")

    async def test_delete_removes_aggregate_and_commits(self) -> None:
        ctx = await _testset_with_items(("doc-1", 0))
        testset_id = next(iter(ctx.evals.testsets))
        commits_before = ctx.uow.commits

        await ctx.service.delete_testset(testset_id)

        self.assertEqual(commits_before + 1, ctx.uow.commits)
        self.assertEqual({}, ctx.evals.testsets)
        self.assertEqual({}, ctx.evals.coords)

    async def test_delete_unknown_testset_raises_keyerror_without_committing(self) -> None:
        ctx = _make()

        with self.assertRaises(KeyError):
            await ctx.service.delete_testset("ghost")

        self.assertEqual(0, ctx.uow.commits)


if __name__ == "__main__":
    import unittest

    unittest.main()
