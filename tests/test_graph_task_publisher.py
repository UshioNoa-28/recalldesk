"""GraphTaskPublisher：领 PENDING → 投队列 → 标 QUEUE；投递失败退避/终态。"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from typing import Any, ClassVar
from unittest import IsolatedAsyncioTestCase

from app.application.services.publish.graph_task_publisher import GraphTaskPublisher
from app.config import GRAPH_TASK_POLICY
from app.domain.graph import GraphTask, GraphTaskStatus


def _entry(attempts: int = 0) -> GraphTask:
    return GraphTask(
        id="task-1",
        document_id="doc-1",
        status=GraphTaskStatus.PENDING,
        attempts=attempts,
        last_error=None,
        created_at=datetime.now(UTC),
        queued_at=None,
    )


class FakeRepository:
    entries: ClassVar[list[GraphTask]] = [_entry()]

    def __init__(self, session: Any, **kwargs: Any) -> None:
        pass

    async def list_pending(self, *, limit: int) -> list[GraphTask]:
        return list(type(self).entries)

    queued: ClassVar[list[str]] = []
    failures: ClassVar[list[str]] = []
    failed: ClassVar[list[str]] = []

    async def mark_queued(self, entry_id: str) -> None:
        type(self).queued.append(entry_id)

    async def record_failure(self, entry_id: str, *, error: str) -> None:
        type(self).failures.append(error)

    async def mark_failed(self, entry_id: str) -> None:
        type(self).failed.append(entry_id)


class FakeQueue:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.enqueued: list[dict] = []

    async def enqueue(self, *, task_id: str, document_id: str) -> str:
        if self.error is not None:
            raise self.error
        self.enqueued.append({"task_id": task_id, "document_id": document_id})
        return "1-0"


class _SessionCtx:
    async def __aenter__(self) -> Any:
        class _S:
            commits = 0

            async def commit(self) -> None:
                _S.commits += 1

        self.session = _S()
        return self.session

    async def __aexit__(self, *args: Any) -> None:
        return None


class _SessionFactory:
    def __call__(self) -> _SessionCtx:
        return _SessionCtx()


class GraphTaskPublisherTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        FakeRepository.entries = [_entry()]
        FakeRepository.queued = []
        FakeRepository.failures = []
        FakeRepository.failed = []
        import app.application.services.publish.graph_task_publisher as module
        self._original = module.SqlAlchemyGraphTaskRepository
        module.SqlAlchemyGraphTaskRepository = FakeRepository
        self.addCleanup(setattr, module, "SqlAlchemyGraphTaskRepository", self._original)

    async def test_publishes_pending_and_marks_queued(self) -> None:
        queue = FakeQueue()
        publisher = GraphTaskPublisher(
            session_factory=_SessionFactory(), queue=queue, policy=GRAPH_TASK_POLICY
        )

        published = await publisher.publish_pending_once()

        self.assertEqual(1, published)
        self.assertEqual([{"task_id": "task-1", "document_id": "doc-1"}], queue.enqueued)
        self.assertEqual(["task-1"], FakeRepository.queued)

    async def test_enqueue_failure_records_backoff(self) -> None:
        queue = FakeQueue(error=ConnectionError("redis down"))
        publisher = GraphTaskPublisher(
            session_factory=_SessionFactory(), queue=queue, policy=GRAPH_TASK_POLICY
        )

        self.assertEqual(0, await publisher.publish_pending_once())
        self.assertTrue(FakeRepository.failures[0].startswith("ConnectionError"))

    async def test_enqueue_failure_at_max_marks_failed(self) -> None:
        FakeRepository.entries = [_entry(attempts=GRAPH_TASK_POLICY.max_attempts - 1)]
        queue = FakeQueue(error=ConnectionError("redis down"))
        publisher = GraphTaskPublisher(
            session_factory=_SessionFactory(), queue=queue, policy=GRAPH_TASK_POLICY
        )

        await publisher.publish_pending_once()
        self.assertEqual(["task-1"], FakeRepository.failed)


if __name__ == "__main__":
    unittest.main()
