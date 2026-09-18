"""EvalRunConsumer 单元测试（全 fake，不连 PG / Redis / Neo4j）。

一题消息的形状：领取校验 -> 一次检索 -> 回写结果 + 标任务 + 数着收尾。
消费者每个事务都在模块内 new 仓储，所以记录挂在共享 state 上
（与被删掉的 EvalRunExecutor 测试同款手法）。
"""

from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from app.application.services.consume.eval_run_consumer import EvalRunConsumer
from app.domain.eval import (
    ChunkRef,
    EvalItemStatus,
    EvalRun,
    EvalRunItem,
    EvalRunStatus,
    EvalRunTask,
    EvalTaskStatus,
    EvalTestSetItem,
)

NOW = datetime(2026, 9, 12, 0, 0, tzinfo=UTC)


def _task(*, status: EvalTaskStatus = EvalTaskStatus.PENDING, attempts: int = 0) -> EvalRunTask:
    return EvalRunTask(
        id="task-1",
        run_id="run-1",
        item_id="item-1",
        status=status,
        attempts=attempts,
        last_error=None,
        created_at=NOW,
        queued_at=NOW,
    )


def _run(*, status: EvalRunStatus = EvalRunStatus.RUNNING) -> EvalRun:
    return EvalRun(
        id="run-1",
        testset_id="ts-1",
        status=status,
        config={"top_k": 5, "query_rewrite": False},
        metrics=None,
        error_message=None,
        created_at=NOW,
        finished_at=None,
        progress_done=0,
        progress_total=1,
    )


def _item(*, query: str | None = "豆腐有多少蛋白质？") -> EvalTestSetItem:
    return EvalTestSetItem(
        id="item-1",
        status=EvalItemStatus.READY,
        query=query,
        evidence=[ChunkRef("doc-1", 2)],
    )


HIT = [{"document_id": "doc-1", "chunk_index": 2, "score": 0.9}]


class State:
    """共享记录：假仓储每次 new 都指向这里。"""

    def __init__(self, **overrides: Any) -> None:
        self.task: EvalRunTask | None = _task()
        self.run: EvalRun | None = _run()
        self.item: EvalTestSetItem | None = _item()
        self.has_result = False
        self.counts: dict[str, int] = {"success": 1}
        self.successes: list[str] = []
        self.faileds: list[str] = []
        self.failures: list[tuple[str, str]] = []
        self.finalized: list[tuple[str, int, int]] = []
        self.recorded: list[EvalRunItem] = []
        for key, value in overrides.items():
            setattr(self, key, value)


class FakeSession:
    def __init__(self, state: State) -> None:
        self.state = state
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class FakeSessionFactory:
    def __init__(self, state: State) -> None:
        self.session = FakeSession(state)

    def __call__(self) -> FakeSessionFactory:
        return self

    async def __aenter__(self) -> FakeSession:
        return self.session

    async def __aexit__(self, *args: Any) -> None:
        return None


def _fake_task_repo(state: State) -> type:
    class Fake:
        def __init__(self, session: FakeSession, **_kwargs) -> None:
            pass

        async def get(self, task_id: str) -> EvalRunTask | None:
            return state.task

        async def mark_success(self, task_id: str) -> None:
            state.successes.append(task_id)

        async def record_failure(self, task_id: str, *, error: str) -> None:
            state.failures.append((task_id, error))

        async def mark_failed(self, task_id: str) -> None:
            state.faileds.append(task_id)

        async def count_by_status(self, run_id: str) -> dict[str, int]:
            return state.counts

    return Fake


def _fake_eval_repo(state: State) -> type:
    class Fake:
        def __init__(self, session: FakeSession, **_kwargs) -> None:
            pass

        async def get_run(self, run_id: str) -> EvalRun | None:
            return state.run

        async def has_run_result(self, run_id: str, item_id: str) -> bool:
            return state.has_result

        async def get_item(self, item_id: str) -> EvalTestSetItem | None:
            return state.item

        async def record_run_item(self, run_id: str, result: EvalRunItem) -> None:
            state.recorded.append(result)

        async def finalize_run(
            self, run_id: str, *, pending_open: int, failed: int
        ) -> None:
            state.finalized.append((run_id, pending_open, failed))

    return Fake


class FakeSearchService:
    def __init__(self, *, raises: Exception | None = None) -> None:
        self.raises = raises
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, *, top_k: int) -> list[dict]:
        self.calls.append((query, top_k))
        if self.raises is not None:
            raise self.raises
        return HIT


class FakeQueue:
    def __init__(self) -> None:
        self.acked: list[str] = []

    async def ensure_consumer_group(self) -> None:
        return None

    async def ack(self, message_id: str) -> None:
        self.acked.append(message_id)


def _make(state: State, search: FakeSearchService | None = None) -> SimpleNamespace:
    queue = FakeQueue()
    search = search or FakeSearchService()
    factory = FakeSessionFactory(state)
    consumer = EvalRunConsumer(
        queue=queue,  # type: ignore[arg-type]
        session_factory=factory,  # type: ignore[arg-type]
        search_service=search,  # type: ignore[arg-type]
        consumer_name="test-consumer",
    )
    return SimpleNamespace(
        consumer=consumer, queue=queue, search=search, factory=factory
    )


class HandleTaskTests(IsolatedAsyncioTestCase):
    async def _handle(self, state: State, **kw: Any) -> SimpleNamespace:
        ctx = _make(state, **kw)
        with patch(
            "app.application.services.consume.eval_run_consumer.SqlAlchemyEvalRunTaskRepository",
            _fake_task_repo(state),
        ), patch(
            "app.application.services.consume.eval_run_consumer.SqlAlchemyEvalRunRepository",
            _fake_eval_repo(state),
        ), patch(
            "app.application.services.consume.eval_run_consumer.SqlAlchemyEvalRepository",
            _fake_eval_repo(state),
        ):
            await ctx.consumer._handle_task(
                task_id="task-1", run_id="run-1", item_id="item-1"
            )
        return ctx

    async def test_happy_path_scores_finalizes_and_commits(self) -> None:
        state = State()

        ctx = await self._handle(state)

        # 检索一次：题面 + run 快照里的 k（不是 settings 的全局值）
        self.assertEqual([("豆腐有多少蛋白质？", 5)], ctx.search.calls)
        self.assertEqual(1, len(state.recorded))
        result = state.recorded[0]
        self.assertEqual("item-1", result.testset_item_id)
        self.assertEqual(1, result.hit_rank)  # 期望切片就是第一条命中
        self.assertEqual(1, result.joint_hit)  # 块级全在
        self.assertGreaterEqual(result.latency_ms, 0.0)
        self.assertEqual(["task-1"], state.successes)
        # 收尾：fake 的 counts 只有 success -> 无在途无失败
        self.assertEqual([("run-1", 0, 0)], state.finalized)
        # 领取段只读不提交，只有回写段提交一次
        self.assertEqual(1, ctx.factory.session.commits)

    async def test_missing_task_still_tries_to_settle_the_run(self) -> None:
        """级联删掉任务行时，这条消息可能就是最后一片在途：finalize 一把，
        在途没清零它是空操作，清了 run 就不会永远挂着。"""

        state = State(task=None)

        await self._handle(state)

        self.assertEqual([("run-1", 0, 0)], state.finalized)
        self.assertEqual([], state.recorded)

    async def test_terminal_task_is_skipped(self) -> None:
        state = State(task=_task(status=EvalTaskStatus.SUCCESS))

        await self._handle(state)

        self.assertEqual([], state.successes)
        self.assertEqual([], state.finalized)

    async def test_finished_run_consumes_task_without_searching(self) -> None:
        state = State(run=_run(status=EvalRunStatus.DONE))

        await self._handle(state)

        self.assertEqual(["task-1"], state.successes)
        self.assertEqual([], state.recorded)

    async def test_vanished_run_consumes_task_without_searching(self) -> None:
        state = State(run=None)

        await self._handle(state)

        self.assertEqual(["task-1"], state.successes)
        self.assertEqual([], state.finalized)

    async def test_existing_result_short_circuits_without_second_search(self) -> None:
        """上一手写了结果行但没来得及标任务：redelivery 补记即可，别重复问。"""

        state = State(has_result=True)

        await self._handle(state)

        self.assertEqual(["task-1"], state.successes)
        self.assertEqual([], state.recorded)
        self.assertEqual([("run-1", 0, 0)], state.finalized)

    async def test_question_without_query_fails_permanently(self) -> None:
        # counts 模拟「该任务刚被标 failed」后的全局状态（真仓储同事务可见）
        state = State(item=_item(query=None), counts={"failed": 1})

        await self._handle(state)

        self.assertEqual([], state.recorded)
        self.assertEqual(["task-1"], state.faileds)
        self.assertEqual([("run-1", 0, 1)], state.finalized)

    async def test_search_failure_below_max_retries_without_finalize(self) -> None:
        state = State(task=_task(attempts=1))

        await self._handle(state, search=FakeSearchService(raises=ConnectionError("neo4j down")))

        self.assertEqual(1, len(state.failures))
        self.assertEqual([], state.faileds)  # 未超限：任务回 PENDING 等重投
        self.assertEqual([], state.finalized)

    async def test_search_failure_at_max_fails_task_and_settles_run(self) -> None:
        """回归的等价物：最后一题永久失败时若没人 finalize，run 会永远 running。"""

        state = State(
            task=_task(attempts=3),  # fake get 返回同一对象：attempts 已达上限
            counts={"success": 0, "failed": 1},
        )

        await self._handle(state, search=FakeSearchService(raises=TimeoutError("llm timeout")))

        self.assertEqual(["task-1"], state.faileds)
        self.assertEqual([("run-1", 0, 1)], state.finalized)


class ProcessMessageAckTests(IsolatedAsyncioTestCase):
    async def test_successful_handling_acks(self) -> None:
        state = State()
        ctx = _make(state)
        with patch(
            "app.application.services.consume.eval_run_consumer.SqlAlchemyEvalRunTaskRepository",
            _fake_task_repo(state),
        ), patch(
            "app.application.services.consume.eval_run_consumer.SqlAlchemyEvalRunRepository",
            _fake_eval_repo(state),
        ), patch(
            "app.application.services.consume.eval_run_consumer.SqlAlchemyEvalRepository",
            _fake_eval_repo(state),
        ):
            await ctx.consumer._process_single_message(
                "1-0", {"task_id": "task-1", "run_id": "run-1", "item_id": "item-1"}
            )

        self.assertEqual(["1-0"], ctx.queue.acked)

    async def test_message_without_fields_is_acked_away(self) -> None:
        ctx = _make(State())

        await ctx.consumer._process_single_message("2-0", {"task_id": "task-1"})

        self.assertEqual(["2-0"], ctx.queue.acked)

    async def test_commit_failure_leaves_message_unacked(self) -> None:
        """不 ACK 才能被 XAUTOCLAIM 重投（DB 状态未变，幂等兜住）。"""

        state = State()
        ctx = _make(state)

        async def _boom(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("db gone")

        with patch(
            "app.application.services.consume.eval_run_consumer.SqlAlchemyEvalRunTaskRepository",
            _fake_task_repo(state),
        ), patch(
            "app.application.services.consume.eval_run_consumer.SqlAlchemyEvalRunRepository",
            _fake_eval_repo(state),
        ), patch.object(EvalRunConsumer, "_handle_task", _boom):
            await ctx.consumer._process_single_message(
                "3-0", {"task_id": "task-1", "run_id": "run-1", "item_id": "item-1"}
            )

        self.assertEqual([], ctx.queue.acked)


class RunLoopTests(IsolatedAsyncioTestCase):
    async def test_run_stops_immediately_when_stop_event_set(self) -> None:
        consumer = EvalRunConsumer(
            queue=FakeQueue(),  # type: ignore[arg-type]
            session_factory=None,  # type: ignore[arg-type]
            search_service=None,  # type: ignore[arg-type]
        )
        stop_event = asyncio.Event()
        stop_event.set()

        await consumer.run(stop_event)  # 立即返回不抛异常


if __name__ == "__main__":
    unittest.main()
