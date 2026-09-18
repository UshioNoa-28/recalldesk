"""EvalService 用例测试（全 fake，不连 PG / Neo4j）：建集、加题、列表 / 详情 / 删除。"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

from app.application.services.evaluation.eval_service import DEFAULT_TESTSET_NAME, EvalService
from app.domain.documents import Document, DocumentStatus
from app.domain.eval import ChunkRef, EvalItemStatus, EvalTestSet, EvalTestSetItem, TestSetStatus

CREATED_AT = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def _refs(*pairs: tuple[str, int]) -> list[ChunkRef]:
    """测试里少写点样板：(document_id, chunk_index) -> ChunkRef。"""

    return [
        ChunkRef(document_id=document_id, chunk_index=index)
        for document_id, index in pairs
    ]


def _groups(*pairs: tuple[str, int]) -> list[list[ChunkRef]]:
    """每坐标一元组：等价于旧的「一块一题」。"""

    return [[ref] for ref in _refs(*pairs)]


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
    """按「证据组」存题目（一组一题，证据平权），
    item id 留到 list 时才生成（真仓储靠 flush，同理）。"""

    def __init__(self) -> None:
        self.testsets: dict[str, EvalTestSet] = {}
        self.groups: dict[str, list[list[ChunkRef]]] = {}
        self.reopened: list[str] = []
        # 测试用来摆布条目状态（默认 pending），retried 记录重置调用；
        # id -> 首块坐标 的反查表在 list 时顺手填好（真仓储里 id 就是主键）
        self.item_status: dict[tuple[str, int], EvalItemStatus] = {}
        self.retried: list[str] = []
        self.id_to_coord: dict[str, tuple[str, int]] = {}

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
        self.groups[testset_id] = []

    async def add_testset_items(
        self, testset_id: str, groups: list[list[ChunkRef]]
    ) -> list[str]:
        start = len(self.groups.get(testset_id, []))
        self.groups.setdefault(testset_id, []).extend(groups)
        return [f"{testset_id}-item-{start + i}" for i in range(len(groups))]

    async def reopen_testset(self, testset_id: str) -> None:
        self.reopened.append(testset_id)
        testset = self.testsets[testset_id]
        testset.status = TestSetStatus.GENERATING
        testset.error_message = None

    async def list_testset_items(self, testset_id: str) -> list[EvalTestSetItem]:
        items = []
        for index, group in enumerate(self.groups.get(testset_id, [])):
            head = group[0]  # 假件图省事用首块坐标当状态键（真仓储按 item id）
            item_id = f"{testset_id}-item-{index}"
            coord = (head.document_id, head.chunk_index)
            self.id_to_coord[item_id] = coord
            items.append(
                EvalTestSetItem(
                    id=item_id,
                    status=self.item_status.get(coord, EvalItemStatus.PENDING),
                    evidence=list(group),
                )
            )
        return items

    async def set_item_pending_retry(self, item_id: str) -> None:
        coord = self.id_to_coord[item_id]
        self.item_status[coord] = EvalItemStatus.PENDING
        self.retried.append(item_id)

    async def get_testset(self, testset_id: str) -> EvalTestSet | None:
        testset = self.testsets.get(testset_id)
        if testset is None:
            return None
        testset.progress_total = len(self.groups.get(testset_id, []))
        return testset

    async def list_testsets(self) -> list[EvalTestSet]:
        for testset_id in self.testsets:
            await self.get_testset(testset_id)
        return list(self.testsets.values())

    async def delete_testset(self, testset_id: str) -> None:
        self.testsets.pop(testset_id, None)
        self.groups.pop(testset_id, None)


class FakeEvalTaskRepository:
    def __init__(self) -> None:
        self.added: list[tuple[str, str]] = []
        self.reset: list[str] = []

    async def add(self, *, testset_id: str, item_id: str) -> None:
        self.added.append((testset_id, item_id))

    async def reset_for_retry(self, *, item_id: str) -> None:
        self.reset.append(item_id)


class FakeDocumentRepository:
    def __init__(self, documents: dict[str, Document]) -> None:
        self._documents = documents

    async def get(self, document_id: str) -> Document | None:
        return self._documents.get(document_id)


class FakeChunkIndex:
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
    vectors = FakeChunkIndex(
        {"doc-1": [_chunk(0), _chunk(1)]} if chunks is None else chunks
    )
    service = EvalService(
        eval_repository=evals,
        eval_task_repository=tasks,
        documents=FakeDocumentRepository(
            {"doc-1": _document()} if documents is None else documents
        ),
        chunk_index=vectors,
        unit_of_work=uow,
    )
    return SimpleNamespace(service=service, evals=evals, tasks=tasks, uow=uow, vectors=vectors)


async def _testset_with_items(*pairs: tuple[str, int]) -> SimpleNamespace:
    """建一个集并加好题：读/删用例的前置状态。"""

    ctx = _make()
    await ctx.service.create_testset(name="水果题集")
    testset_id = next(iter(ctx.evals.testsets))
    await ctx.service.add_items(testset_id, _groups(*pairs))
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

        result = await ctx.service.add_items(testset_id, _groups(("doc-1", 0), ("doc-1", 1)))

        self.assertEqual(2, ctx.uow.commits)  # 建集一次、加题一次
        self.assertEqual(
            _groups(("doc-1", 0), ("doc-1", 1)), ctx.evals.groups[testset_id]
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
                        "evidence": [{"document_id": "doc-1", "chunk_index": i}],
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

        await ctx.service.add_items(testset_id, _groups(("doc-1", 1)))

        self.assertEqual([testset_id], ctx.evals.reopened)
        self.assertEqual("generating", ctx.evals.testsets[testset_id].status.value)
        self.assertIsNone(ctx.evals.testsets[testset_id].error_message)

    async def test_duplicates_are_all_created(self) -> None:
        """平权裁决：批内重复、与集内重复都不再查——同块多题随便出。"""

        ctx = await _testset_with_items(("doc-1", 0))
        testset_id = next(iter(ctx.evals.testsets))
        ctx.tasks.added.clear()

        result = await ctx.service.add_items(
            testset_id, _groups(("doc-1", 1), ("doc-1", 1), ("doc-1", 0))
        )

        self.assertEqual(
            _groups(("doc-1", 0), ("doc-1", 1), ("doc-1", 1), ("doc-1", 0)),
            ctx.evals.groups[testset_id],
        )
        self.assertEqual(
            [(testset_id, f"{testset_id}-item-{i}") for i in (1, 2, 3)], ctx.tasks.added
        )
        self.assertEqual(4, result["progress_total"])

    async def test_empty_groups_writes_nothing_and_keeps_status(self) -> None:
        """一组都没有：不能 reopen，没有任务就没人 finalize，集会卡在 generating。"""

        ctx = await _testset_with_items(("doc-1", 0))
        testset_id = next(iter(ctx.evals.testsets))
        ctx.evals.testsets[testset_id].status = TestSetStatus.READY
        commits_before = ctx.uow.commits
        ctx.tasks.added.clear()
        ctx.evals.reopened.clear()

        result = await ctx.service.add_items(testset_id, [])

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
            testset_id, _groups(("doc-1", 0), ("doc-1", 1), ("doc-2", 0))
        )

        self.assertEqual(["doc-1", "doc-2"], ctx.vectors.scrolled)

    async def test_unknown_testset_raises_keyerror_without_committing(self) -> None:
        ctx = _make()

        with self.assertRaises(KeyError):
            await ctx.service.add_items("ghost", _groups(("doc-1", 0)))

        self.assertEqual(0, ctx.uow.commits)
        self.assertEqual([], ctx.tasks.added)

    async def test_missing_document_raises_value_error_without_committing(self) -> None:
        ctx = _make(documents={})
        await ctx.service.create_testset(name="x")
        testset_id = next(iter(ctx.evals.testsets))
        commits_before = ctx.uow.commits

        with self.assertRaises(ValueError) as exc:
            await ctx.service.add_items(testset_id, _groups(("ghost", 0)))

        self.assertIn("不存在", str(exc.exception))
        self.assertEqual(commits_before, ctx.uow.commits)
        self.assertEqual([], ctx.tasks.added)

    async def test_unknown_chunk_index_raises_value_error_without_committing(self) -> None:
        ctx = _make()
        await ctx.service.create_testset(name="x")
        testset_id = next(iter(ctx.evals.testsets))
        commits_before = ctx.uow.commits

        with self.assertRaises(ValueError) as exc:
            await ctx.service.add_items(testset_id, _groups(("doc-1", 0), ("doc-1", 9)))

        self.assertIn("切片 #9", str(exc.exception))
        self.assertEqual(commits_before, ctx.uow.commits)
        self.assertEqual([], ctx.tasks.added)
        self.assertNotIn(testset_id, ctx.evals.reopened)

    async def test_multi_evidence_group_writes_one_item_with_full_evidence(self) -> None:
        """一组三块（跨两文档）= 一道多跳题：一条任务，证据集合完整落库。"""

        ctx = _make(
            documents={"doc-1": _document(), "doc-2": _document("doc-2", "其他.txt")},
            chunks={"doc-1": [_chunk(0), _chunk(1)], "doc-2": [_chunk(0)]},
        )
        await ctx.service.create_testset(name="多跳")
        testset_id = next(iter(ctx.evals.testsets))

        result = await ctx.service.add_items(
            testset_id,
            [_refs(("doc-1", 0), ("doc-2", 0), ("doc-1", 1))],
        )

        self.assertEqual(
            [[ChunkRef("doc-1", 0), ChunkRef("doc-2", 0), ChunkRef("doc-1", 1)]],
            ctx.evals.groups[testset_id],
        )
        self.assertEqual([(testset_id, f"{testset_id}-item-0")], ctx.tasks.added)
        self.assertEqual(1, result["progress_total"])  # 一组就是一题
        self.assertEqual(
            [
                {"document_id": "doc-1", "chunk_index": 0},
                {"document_id": "doc-2", "chunk_index": 0},
                {"document_id": "doc-1", "chunk_index": 1},
            ],
            result["items"][0]["evidence"],
        )

    async def test_group_over_evidence_cap_raises_without_writing(self) -> None:
        ctx = _make(
            chunks={
                "doc-1": [_chunk(i) for i in range(7)],
            }
        )
        await ctx.service.create_testset(name="x")
        testset_id = next(iter(ctx.evals.testsets))

        with self.assertRaises(ValueError) as exc:
            await ctx.service.add_items(testset_id, [_refs(*(("doc-1", i) for i in range(6)))])

        self.assertIn("最多", str(exc.exception))
        self.assertEqual([], ctx.evals.groups[testset_id])
        self.assertEqual([], ctx.tasks.added)

    async def test_duplicate_coords_within_group_collapse(self) -> None:
        ctx = _make()
        await ctx.service.create_testset(name="x")
        testset_id = next(iter(ctx.evals.testsets))

        await ctx.service.add_items(
            testset_id, [_refs(("doc-1", 0), ("doc-1", 1), ("doc-1", 0))]
        )

        self.assertEqual(_refs(("doc-1", 0), ("doc-1", 1)), ctx.evals.groups[testset_id][0])

    async def test_group_sharing_first_coord_is_still_created(self) -> None:
        """旧"一 chunk 一题"退役：首块相同、证据不同的组照出不误。"""

        ctx = await _testset_with_items(("doc-1", 0))
        testset_id = next(iter(ctx.evals.testsets))
        ctx.tasks.added.clear()

        await ctx.service.add_items(testset_id, [_refs(("doc-1", 0), ("doc-1", 1))])

        self.assertEqual(2, len(ctx.evals.groups[testset_id]))
        self.assertEqual([(testset_id, f"{testset_id}-item-1")], ctx.tasks.added)

    async def test_missing_evidence_coordinate_raises_without_committing(self) -> None:
        """证据平权同等待遇：任一块没索引就整组拒绝，不落半题。"""

        ctx = _make()
        await ctx.service.create_testset(name="x")
        testset_id = next(iter(ctx.evals.testsets))
        commits_before = ctx.uow.commits

        with self.assertRaises(ValueError) as exc:
            await ctx.service.add_items(testset_id, [_refs(("doc-1", 0), ("doc-1", 9))])

        self.assertIn("切片 #9", str(exc.exception))
        self.assertEqual(commits_before, ctx.uow.commits)
        self.assertEqual([], ctx.evals.groups[testset_id])


class EvalServiceRetryFailedItemsTests(IsolatedAsyncioTestCase):
    """重试失败题目：只碰 FAILED，条目与任务一起复位。"""

    async def test_retries_only_failed_items_in_one_transaction(self) -> None:
        ctx = _make()
        await ctx.service.create_testset(name="水果题集")
        testset_id = next(iter(ctx.evals.testsets))
        await ctx.service.add_items(testset_id, _groups(("doc-1", 0), ("doc-1", 1)))
        # 摆布历史：第 0 题出题失败，第 1 题还在生成路上
        ctx.evals.item_status[("doc-1", 0)] = EvalItemStatus.FAILED
        commits_before = ctx.uow.commits

        result = await ctx.service.retry_failed_items(testset_id)

        self.assertEqual([f"{testset_id}-item-0"], ctx.evals.retried)
        self.assertEqual([f"{testset_id}-item-0"], ctx.tasks.reset)
        self.assertEqual(2, ctx.evals.reopened.count(testset_id))  # add_items 那次 + 这次
        self.assertEqual(1, ctx.uow.commits - commits_before)
        statuses = {item["evidence"][0]["chunk_index"]: item["status"] for item in result["items"]}
        self.assertEqual({0: "pending", 1: "pending"}, statuses)

    async def test_no_failed_items_is_a_noop(self) -> None:
        ctx = _make()
        await ctx.service.create_testset(name="水果题集")
        testset_id = next(iter(ctx.evals.testsets))
        await ctx.service.add_items(testset_id, _groups(("doc-1", 0)))
        commits_before = ctx.uow.commits
        reopened_before = list(ctx.evals.reopened)

        result = await ctx.service.retry_failed_items(testset_id)

        self.assertEqual([], ctx.tasks.reset)
        # 没活干绝不 reopen：没有任务就没人再 finalize，集会卡在 generating
        self.assertEqual(reopened_before, ctx.evals.reopened)
        self.assertEqual(0, ctx.uow.commits - commits_before)
        self.assertEqual("generating", result["status"])

    async def test_missing_testset_raises_key_error(self) -> None:
        ctx = _make()

        with self.assertRaises(KeyError):
            await ctx.service.retry_failed_items("nope")


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
        self.assertEqual({}, ctx.evals.groups)

    async def test_delete_unknown_testset_raises_keyerror_without_committing(self) -> None:
        ctx = _make()

        with self.assertRaises(KeyError):
            await ctx.service.delete_testset("ghost")

        self.assertEqual(0, ctx.uow.commits)


if __name__ == "__main__":
    import unittest

    unittest.main()
