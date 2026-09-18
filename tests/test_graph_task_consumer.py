"""GraphTaskConsumer：领任务 → 抽取 → 整篇写图；失败退避、幂等、级联缺失。"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from typing import Any, ClassVar
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from app.application.services.consume.graph_task_consumer import GraphTaskConsumer
from app.config import GRAPH_TASK_POLICY
from app.domain.graph import GraphEntity, GraphTask, GraphTaskStatus

_MODULE = "app.application.services.consume.graph_task_consumer"


def _task(
    task_id: str = "task-1",
    status: GraphTaskStatus = GraphTaskStatus.QUEUE,
    attempts: int = 0,
) -> GraphTask:
    return GraphTask(
        id=task_id,
        document_id="doc-1",
        status=status,
        attempts=attempts,
        last_error=None,
        created_at=datetime.now(UTC),
        queued_at=datetime.now(UTC),
    )


class FakeGraphTaskRepository:
    task: ClassVar[GraphTask | None] = _task()

    def __init__(self, session: Any, **kwargs: Any) -> None:
        pass

    async def get(self, entry_id: str) -> GraphTask | None:
        return type(self).task

    async def mark_success(self, entry_id: str) -> None:
        assert type(self).task is not None
        type(self).task.status = GraphTaskStatus.SUCCESS

    async def mark_failed(self, entry_id: str) -> None:
        assert type(self).task is not None
        type(self).task.status = GraphTaskStatus.FAILED

    async def record_failure(self, entry_id: str, *, error: str) -> None:
        assert type(self).task is not None
        type(self).task.attempts += 1
        type(self).task.last_error = error


class FakeDocument:
    def __init__(self, doc_id: str = "doc-1", name: str = "a.txt") -> None:
        self.id, self.name = doc_id, name


class FakeDocumentRepository:
    document: ClassVar[FakeDocument | None] = FakeDocument()

    def __init__(self, session: Any, **kwargs: Any) -> None:
        pass

    async def get(self, document_id: str) -> FakeDocument | None:
        return type(self).document


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class _SessionCtx:
    async def __aenter__(self) -> FakeSession:
        self.session = FakeSession()
        return self.session

    async def __aexit__(self, *args: Any) -> None:
        return None


class FakeSessionFactory:
    def __call__(self) -> _SessionCtx:
        return _SessionCtx()


class FakeChunkIndex:
    def __init__(self, chunks: list[dict] | None = None) -> None:
        self.chunks = [] if chunks is None else chunks

    async def get_document_chunks(self, *, document_id: str) -> list[dict]:
        return self.chunks


class FakeContribution:
    entities: ClassVar[list[GraphEntity]] = [GraphEntity(name_norm="苹果", name="苹果")]
    triples: ClassVar[list[dict]] = []


class FakeExtraction:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.built: list[tuple[str, int]] = []

    async def build(self, document_name: str, chunks: list[dict]) -> FakeContribution:
        if self.error is not None:
            raise self.error
        self.built.append((document_name, len(chunks)))
        return FakeContribution()


class FakeGraphRepository:
    def __init__(self) -> None:
        self.upserts: list[dict] = []
        self.deleted: list[str] = []

    async def upsert_document_graph(self, *, document_id: str, entities, triples) -> int:
        self.upserts.append({"document_id": document_id, "entities": entities})
        return len(entities)

    async def delete_document_graph(self, document_id: str) -> None:
        self.deleted.append(document_id)


def _build(extraction=None, index=None, graph=None) -> GraphTaskConsumer:
    return GraphTaskConsumer(
        queue=Any,  # 本组测试不跑 run 循环，queue 不会被触碰
        session_factory=FakeSessionFactory(),
        extraction_service=extraction or FakeExtraction(),
        graph=graph or FakeGraphRepository(),
        chunk_index=index or FakeChunkIndex([{"chunk_index": 0, "text": "t"}]),
        policy=GRAPH_TASK_POLICY,
    )


class GraphTaskConsumerHandleTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        FakeGraphTaskRepository.task = _task()
        FakeDocumentRepository.document = FakeDocument()
        patcher = patch.multiple(
            _MODULE,
            SqlAlchemyGraphTaskRepository=FakeGraphTaskRepository,
            SqlAlchemyDocumentRepository=FakeDocumentRepository,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_success_upserts_graph_and_marks_task(self) -> None:
        graph = FakeGraphRepository()
        consumer = _build(graph=graph)

        await consumer._handle_task(task_id="task-1", document_id="doc-1")

        self.assertEqual(GraphTaskStatus.SUCCESS, FakeGraphTaskRepository.task.status)
        self.assertEqual(1, len(graph.upserts))
        self.assertEqual("doc-1", graph.upserts[0]["document_id"])

    async def test_terminal_task_is_idempotent_noop(self) -> None:
        FakeGraphTaskRepository.task = _task(status=GraphTaskStatus.SUCCESS)
        graph = FakeGraphRepository()

        await _build(graph=graph)._handle_task(task_id="task-1", document_id="doc-1")

        self.assertEqual([], graph.upserts)

    async def test_missing_document_consumes_task(self) -> None:
        FakeDocumentRepository.document = None

        await _build()._handle_task(task_id="task-1", document_id="doc-1")

        self.assertEqual(GraphTaskStatus.SUCCESS, FakeGraphTaskRepository.task.status)

    async def test_no_chunks_consumes_without_extraction(self) -> None:
        extraction = FakeExtraction()
        consumer = _build(extraction=extraction, index=FakeChunkIndex([]))

        await consumer._handle_task(task_id="task-1", document_id="doc-1")

        self.assertEqual([], extraction.built)
        self.assertEqual(GraphTaskStatus.SUCCESS, FakeGraphTaskRepository.task.status)

    async def test_extraction_failure_backs_off_below_max(self) -> None:
        FakeGraphTaskRepository.task = _task(attempts=GRAPH_TASK_POLICY.max_attempts - 2)

        await _build(extraction=FakeExtraction(error=RuntimeError("llm down")))._handle_task(
            task_id="task-1", document_id="doc-1"
        )

        task = FakeGraphTaskRepository.task
        assert task is not None
        self.assertEqual(task.attempts, GRAPH_TASK_POLICY.max_attempts - 1)
        self.assertEqual(GraphTaskStatus.QUEUE, task.status)  # 未超限不终态
        self.assertIn("llm down", task.last_error or "")

    async def test_extraction_failure_at_max_marks_failed(self) -> None:
        FakeGraphTaskRepository.task = _task(attempts=GRAPH_TASK_POLICY.max_attempts - 1)

        await _build(extraction=FakeExtraction(error=RuntimeError("llm down")))._handle_task(
            task_id="task-1", document_id="doc-1"
        )

        self.assertEqual(GraphTaskStatus.FAILED, FakeGraphTaskRepository.task.status)

    async def test_extract_ids_requires_both_fields(self) -> None:
        consumer = _build()
        self.assertIsNone(consumer._extract_task_ids({"task_id": "t"}))
        self.assertEqual(
            {"task_id": "t", "document_id": "d"},
            consumer._extract_task_ids({"task_id": "t", "document_id": "d"}),
        )


class PatchIntegrationTests(IsolatedAsyncioTestCase):
    """真 import 路径可 patch（防重构后测试悄悄失效）。"""

    async def test_module_imports_are_patchable(self) -> None:
        with patch.multiple(_MODULE, SqlAlchemyGraphTaskRepository=FakeGraphTaskRepository,
                            SqlAlchemyDocumentRepository=FakeDocumentRepository):
            await _build()._handle_task(task_id="task-1", document_id="doc-1")


if __name__ == "__main__":
    unittest.main()
