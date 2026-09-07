"""EvalTaskPublisher 投递逻辑测试（fake queue + fake eval task repo）。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from app.application.services.publish.eval_task_publisher import EvalTaskPublisher
from app.domain.eval import EvalTask, EvalTaskStatus
from settings import settings


def _entry(task_id: str = "task-1", attempts: int = 0) -> EvalTask:
    return EvalTask(
        id=task_id,
        testset_id="ts-1",
        item_id="item-1",
        status=EvalTaskStatus.PENDING,
        attempts=attempts,
        last_error=None,
        created_at=datetime.now(UTC),
        queued_at=None,
    )


class FakeQueue:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.enqueued: list[tuple[str, str]] = []

    async def enqueue(self, *, task_id: str, item_id: str) -> str:
        if self.fail:
            raise ConnectionError("redis down")
        self.enqueued.append((task_id, item_id))
        return "1-0"


class FakeEvalTasks:
    def __init__(self) -> None:
        self.queued: list[str] = []
        self.failed_entries: list[str] = []
        self.recorded_failures: list[str] = []

    async def mark_queued(self, task_id: str) -> None:
        self.queued.append(task_id)

    async def record_failure(self, task_id: str, *, error: str) -> None:
        self.recorded_failures.append(task_id)

    async def mark_failed(self, task_id: str) -> None:
        self.failed_entries.append(task_id)


class FakeEvalRepository:
    """题目/测试集侧：永久失败的任务要把条目一起收尾。"""

    def __init__(self) -> None:
        self.items_failed: list[tuple[str, str]] = []
        self.finalized: list[str] = []

    async def set_item_failed(self, item_id: str, *, error: str) -> None:
        self.items_failed.append((item_id, error))

    async def finalize_testset(self, testset_id: str) -> None:
        self.finalized.append(testset_id)


def _publisher(queue: FakeQueue) -> EvalTaskPublisher:
    return EvalTaskPublisher(session_factory=None, queue=queue)


class EvalTaskPublisherPublishOneTests(IsolatedAsyncioTestCase):
    """_publish_one：成功标 QUEUE；失败记一次错误，超限标 FAILED 并收尾条目。"""

    async def test_publish_success_marks_queued(self) -> None:
        queue = FakeQueue()
        tasks = FakeEvalTasks()
        evals = FakeEvalRepository()

        result = await _publisher(queue)._publish_one(_entry(), tasks, evals)

        self.assertEqual(1, result)
        self.assertEqual([("task-1", "item-1")], queue.enqueued)
        self.assertEqual(["task-1"], tasks.queued)
        self.assertEqual([], evals.finalized)  # 成功投递不影响条目

    async def test_publish_failure_below_max_keeps_pending(self) -> None:
        queue = FakeQueue(fail=True)
        tasks = FakeEvalTasks()
        evals = FakeEvalRepository()

        result = await _publisher(queue)._publish_one(_entry(attempts=1), tasks, evals)

        self.assertEqual(0, result)
        self.assertEqual(["task-1"], tasks.recorded_failures)
        self.assertEqual([], tasks.failed_entries)  # 未超限，不标终态
        self.assertEqual([], evals.items_failed)  # 条目仍在重试，不收尾

    async def test_publish_failure_at_max_marks_failed_and_settles_item(self) -> None:
        """回归：任务永久失败时以前只标 task，item 停在 pending →
        测试集永远等在 generating。"""

        queue = FakeQueue(fail=True)
        tasks = FakeEvalTasks()
        evals = FakeEvalRepository()

        result = await _publisher(queue)._publish_one(
            _entry(attempts=settings.eval_task_max_attempts - 1), tasks, evals
        )

        self.assertEqual(0, result)
        self.assertEqual(["task-1"], tasks.failed_entries)
        self.assertEqual(1, len(evals.items_failed))
        self.assertEqual("item-1", evals.items_failed[0][0])
        self.assertEqual(["ts-1"], evals.finalized)


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


class EvalTaskPublisherPublishOnceTests(IsolatedAsyncioTestCase):
    """publish_pending_once：批量领取并投递，最后统一 commit。"""

    async def test_publishes_all_pending_and_commits(self) -> None:
        entries = [_entry("task-1"), _entry("task-2")]
        queue = FakeQueue()
        tasks = FakeEvalTasks()
        evals = FakeEvalRepository()

        class FakeRepo:
            def __init__(self, session) -> None:
                self.session = session

            async def list_pending(self, *, limit: int):
                return entries

            async def mark_queued(self, task_id: str) -> None:
                await tasks.mark_queued(task_id)

            async def record_failure(self, task_id: str, *, error: str) -> None:
                await tasks.record_failure(task_id, error=error)

            async def mark_failed(self, task_id: str) -> None:
                await tasks.mark_failed(task_id)

        with patch.multiple(
            "app.application.services.publish.eval_task_publisher",
            SqlAlchemyEvalTaskRepository=FakeRepo,
            SqlAlchemyEvalRepository=lambda session: evals,
        ):
            publisher = EvalTaskPublisher(
                session_factory=_FakeSessionFactory(_FakeSession()),
                queue=queue,
            )
            published = await publisher.publish_pending_once()

        self.assertEqual(2, published)
        self.assertEqual([("task-1", "item-1"), ("task-2", "item-1")], queue.enqueued)
        self.assertEqual(["task-1", "task-2"], tasks.queued)
        self.assertEqual([], evals.finalized)


class EvalTaskPublisherRunLoopTests(IsolatedAsyncioTestCase):
    async def test_run_stops_immediately_when_stop_event_set(self) -> None:
        publisher = EvalTaskPublisher(session_factory=None, queue=FakeQueue())
        stop_event = asyncio.Event()
        stop_event.set()

        await publisher.run(stop_event)  # 应立即返回，不抛异常


if __name__ == "__main__":
    import unittest

    unittest.main()
