"""DocumentTaskPublisher 投递逻辑测试（fake queue + fake outbox）。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from app.application.services.publish.document_task_publisher import DocumentTaskPublisher
from app.domain.documents import DocumentTask, DocumentTaskStatus
from settings import settings


def _entry(task_id: str = "task-1", attempts: int = 0) -> DocumentTask:
    return DocumentTask(
        id=task_id,
        document_id="doc-1",
        operation="index",
        status=DocumentTaskStatus.PENDING,
        attempts=attempts,
        last_error=None,
        created_at=datetime.now(UTC),
        queued_at=None,
    )


class FakeQueue:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.enqueued: list[tuple[str, str, str]] = []

    async def enqueue(self, *, task_id: str, document_id: str, operation: str) -> str:
        if self.fail:
            raise ConnectionError("redis down")
        self.enqueued.append((task_id, document_id, operation))
        return "1-0"


class FakeOutbox:
    def __init__(self) -> None:
        self.queued: list[str] = []
        self.failed_entries: list[str] = []
        self.recorded_failures: list[str] = []

    async def mark_queued(self, entry_id: str) -> None:
        self.queued.append(entry_id)

    async def record_failure(self, entry_id: str, *, error: str) -> None:
        self.recorded_failures.append(entry_id)

    async def mark_failed(self, entry_id: str) -> None:
        self.failed_entries.append(entry_id)


def _publisher(queue: FakeQueue) -> DocumentTaskPublisher:
    return DocumentTaskPublisher(session_factory=None, queue=queue)


class TaskPublisherPublishOneTests(IsolatedAsyncioTestCase):
    """_publish_one：成功标 QUEUE；失败记一次错误，超限标 FAILED。"""

    async def test_publish_success_marks_queued(self) -> None:
        queue = FakeQueue()
        outbox = FakeOutbox()

        result = await _publisher(queue)._publish_one(_entry(), outbox)

        self.assertEqual(1, result)
        self.assertEqual([("task-1", "doc-1", "index")], queue.enqueued)
        self.assertEqual(["task-1"], outbox.queued)

    async def test_publish_failure_below_max_keeps_pending(self) -> None:
        queue = FakeQueue(fail=True)
        outbox = FakeOutbox()

        result = await _publisher(queue)._publish_one(_entry(attempts=1), outbox)

        self.assertEqual(0, result)
        self.assertEqual(["task-1"], outbox.recorded_failures)
        self.assertEqual([], outbox.failed_entries)  # 未超限，不标终态

    async def test_publish_failure_at_max_marks_failed(self) -> None:
        queue = FakeQueue(fail=True)
        outbox = FakeOutbox()

        result = await _publisher(queue)._publish_one(
            _entry(attempts=settings.task_max_attempts - 1),
            outbox,
        )

        self.assertEqual(0, result)
        self.assertEqual(["task-1"], outbox.failed_entries)


class _FakeSession:
    async def commit(self) -> None:
        return None


class _FakeSessionContext:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, *args) -> None:
        return None


class _FakeSessionFactory:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def __call__(self) -> _FakeSessionContext:
        return _FakeSessionContext(self._session)


class TaskPublisherPublishOnceTests(IsolatedAsyncioTestCase):
    """publish_pending_once：批量读取并投递，最后统一 commit。"""

    async def test_publishes_all_pending_and_commits(self) -> None:
        entries = [_entry("task-1"), _entry("task-2")]
        session = _FakeSession()
        queue = FakeQueue()
        outbox = FakeOutbox()

        class FakeRepo:
            def __init__(self, s) -> None:
                self.session = s

            async def list_pending(self, *, limit: int):
                return entries

            async def mark_queued(self, entry_id: str) -> None:
                await outbox.mark_queued(entry_id)

            async def record_failure(self, entry_id: str, *, error: str) -> None:
                await outbox.record_failure(entry_id, error=error)

            async def mark_failed(self, entry_id: str) -> None:
                await outbox.mark_failed(entry_id)

        with patch(
            "app.application.services.publish.document_task_publisher.SqlAlchemyDocumentTaskRepository",
            FakeRepo,
        ):
            publisher = DocumentTaskPublisher(
                session_factory=_FakeSessionFactory(session),
                queue=queue,
            )
            published = await publisher.publish_pending_once()

        self.assertEqual(2, published)
        self.assertEqual(
            [("task-1", "doc-1", "index"), ("task-2", "doc-1", "index")], queue.enqueued
        )
        self.assertEqual(["task-1", "task-2"], outbox.queued)


class TaskPublisherRunLoopTests(IsolatedAsyncioTestCase):
    async def test_run_stops_immediately_when_stop_event_set(self) -> None:
        publisher = DocumentTaskPublisher(session_factory=None, queue=FakeQueue())
        stop_event = asyncio.Event()
        stop_event.set()

        await publisher.run(stop_event)  # 应立即返回，不抛异常


if __name__ == "__main__":
    import unittest

    unittest.main()
