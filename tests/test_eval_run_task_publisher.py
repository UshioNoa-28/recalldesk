"""EvalRunTaskPublisher 投递逻辑测试（fake queue + fake run task repo + fake eval repo）。

与出题 publisher 同族，但收尾不同：投递超限标 FAILED 后必须试 finalize_run，
否则「最后一题恰好投不出去」会让 run 永远停在 running。
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from app.application.services.publish.eval_run_task_publisher import EvalRunTaskPublisher
from app.domain.eval import EvalRunTask, EvalTaskStatus
from settings import settings

NOW = datetime(2026, 9, 12, 0, 0, tzinfo=UTC)


def _entry(*, task_id: str = "task-1", attempts: int = 0) -> EvalRunTask:
    return EvalRunTask(
        id=task_id,
        run_id="run-1",
        item_id="item-1",
        status=EvalTaskStatus.PENDING,
        attempts=attempts,
        last_error=None,
        created_at=NOW,
        queued_at=None,
    )


class FakeQueue:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.enqueued: list[tuple[str, str, str]] = []

    async def enqueue(self, *, task_id: str, run_id: str, item_id: str) -> str:
        if self.fail:
            raise ConnectionError("redis down")
        self.enqueued.append((task_id, run_id, item_id))
        return "1-0"


class FakeRunTasks:
    def __init__(self, *, counts: dict[str, int] | None = None) -> None:
        self.queued: list[str] = []
        self.failed: list[str] = []
        self.failures: list[tuple[str, str]] = []
        self._counts = counts or {"failed": 1}

    async def mark_queued(self, task_id: str) -> None:
        self.queued.append(task_id)

    async def record_failure(self, task_id: str, *, error: str) -> None:
        self.failures.append((task_id, error))

    async def mark_failed(self, task_id: str) -> None:
        self.failed.append(task_id)

    async def count_by_status(self, run_id: str) -> dict[str, int]:
        return self._counts


class FakeEvalRepository:
    def __init__(self) -> None:
        self.finalized: list[tuple[str, int, int]] = []

    async def finalize_run(
        self, run_id: str, *, pending_open: int, failed: int
    ) -> None:
        self.finalized.append((run_id, pending_open, failed))


def _publisher(queue: FakeQueue) -> EvalRunTaskPublisher:
    return EvalRunTaskPublisher(session_factory=None, queue=queue)  # type: ignore[arg-type]


class PublishOneTests(IsolatedAsyncioTestCase):
    async def test_success_marks_queued_without_finalizing(self) -> None:
        queue, tasks, evals = FakeQueue(), FakeRunTasks(), FakeEvalRepository()

        published = await _publisher(queue)._publish_one(_entry(), tasks, evals)

        self.assertEqual(1, published)
        self.assertEqual([("task-1", "run-1", "item-1")], queue.enqueued)
        self.assertEqual(["task-1"], tasks.queued)
        self.assertEqual([], evals.finalized)  # 成功投递不该收尾

    async def test_failure_below_max_retries_without_finalizing(self) -> None:
        queue, tasks, evals = (
            FakeQueue(fail=True),
            FakeRunTasks(),
            FakeEvalRepository(),
        )

        published = await _publisher(queue)._publish_one(
            _entry(attempts=0), tasks, evals
        )

        self.assertEqual(0, published)
        self.assertEqual(1, len(tasks.failures))
        self.assertEqual([], tasks.failed)
        self.assertEqual([], evals.finalized)

    async def test_failure_at_max_fails_task_and_settles_run(self) -> None:
        """回归：最后一题投递永久失败若不 finalize，run 会永远 running。"""

        queue, evals = FakeQueue(fail=True), FakeEvalRepository()
        tasks = FakeRunTasks(counts={"pending": 0, "queue": 0, "failed": 1, "success": 3})
        entry = _entry(attempts=settings.eval_run_task_max_attempts - 1)

        published = await _publisher(queue)._publish_one(entry, tasks, evals)

        self.assertEqual(0, published)
        self.assertEqual(["task-1"], tasks.failed)
        self.assertEqual([("run-1", 0, 1)], evals.finalized)

    async def test_failure_at_max_keeps_run_open_if_tasks_remain(self) -> None:
        """还有在途任务时 finalize 传非 0 pending_open，run 不会提前收尾。"""

        queue, evals = FakeQueue(fail=True), FakeEvalRepository()
        tasks = FakeRunTasks(counts={"pending": 2, "queue": 0, "failed": 1})
        entry = _entry(attempts=settings.eval_run_task_max_attempts - 1)

        await _publisher(queue)._publish_one(entry, tasks, evals)

        self.assertEqual([("run-1", 2, 1)], evals.finalized)


class _FakeSession:
    async def commit(self) -> None:
        return None


class _FakeSessionContext:
    async def __aenter__(self) -> _FakeSession:
        return _FakeSession()

    async def __aexit__(self, *args: object) -> None:
        return None


class _FakeSessionFactory:
    def __call__(self) -> _FakeSessionContext:
        return _FakeSessionContext()


class PublishPendingOnceTests(IsolatedAsyncioTestCase):
    async def test_publishes_batch_then_commits(self) -> None:
        entries = [_entry(task_id="task-1"), _entry(task_id="task-2")]
        queue = FakeQueue()
        evals = FakeEvalRepository()

        class TasksRepo(FakeRunTasks):
            def __init__(self, session: object, **_kwargs) -> None:
                super().__init__()
                self._pending = entries

            async def list_pending(self, *, limit: int) -> list[EvalRunTask]:
                return self._pending

        with patch.multiple(
            "app.application.services.publish.eval_run_task_publisher",
            SqlAlchemyEvalRunTaskRepository=TasksRepo,
            SqlAlchemyEvalRepository=lambda session: evals,
        ):
            publisher = EvalRunTaskPublisher(
                session_factory=_FakeSessionFactory(),  # type: ignore[arg-type]
                queue=queue,
            )
            published = await publisher.publish_pending_once()

        self.assertEqual(2, published)
        self.assertEqual(
            [("task-1", "run-1", "item-1"), ("task-2", "run-1", "item-1")],
            queue.enqueued,
        )


if __name__ == "__main__":
    unittest.main()
