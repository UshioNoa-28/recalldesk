"""EvalRunExecutor 单元测试（假仓储 / 假检索，离线运行）。

跑一次 run 的形状：读 run 与题目 → 一题一次检索一个事务 → 从库里的结果行算
聚合指标 → 一次性收尾。异常都在内部落成 failed，不外抛（那是后台任务）。
"""

from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from app.application.services.eval_run_executor import (
    STALE_RUN_ERROR,
    EvalRunExecutor,
    fail_stale_runs,
)
from app.domain.eval import EvalItemStatus, EvalRun, EvalRunItem, EvalRunStatus, EvalTestSetItem

CREATED_AT = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class FakeSessionFactory:
    """每次调用都给同一个假 session（真工厂每次开一条连接，测试不需要）。"""

    def __init__(self) -> None:
        self.session = FakeSession()

    def __call__(self) -> FakeSessionFactory:
        return self

    async def __aenter__(self) -> FakeSession:
        return self.session

    async def __aexit__(self, *args: Any) -> None:
        return None


class FakeEvalRepository:
    """执行器内部每个事务都自己 new 一个仓储，所以记录只能挂在类上。"""

    instances: list[FakeEvalRepository] = []
    run: EvalRun | None = None
    questions: list[EvalTestSetItem] = []
    stored: list[EvalRunItem] = []  # 库里已有的结果行（模拟补跑剩下的题）
    recorded_rows: list[EvalRunItem] = []
    finished_rows: list[tuple[EvalRunStatus, dict | None, str | None]] = []

    def __init__(self, session: FakeSession) -> None:
        self.session = session
        self.swept: list[str] = []
        FakeEvalRepository.instances.append(self)

    async def get_run(self, run_id: str) -> EvalRun | None:
        return type(self).run if run_id == "run-1" else None

    async def list_unscored_questions(self, run_id: str) -> list[EvalTestSetItem]:
        return type(self).questions

    async def record_run_item(self, run_id: str, result: EvalRunItem) -> None:
        type(self).recorded_rows.append(result)

    async def list_run_items(self, run_id: str) -> list[EvalRunItem]:
        return [*type(self).recorded_rows, *type(self).stored]

    async def finish_run(
        self,
        run_id: str,
        *,
        status: EvalRunStatus,
        metrics: dict | None = None,
        error_message: str | None = None,
    ) -> None:
        type(self).finished_rows.append((status, metrics, error_message))

    async def fail_stale_runs(self, *, error: str) -> int:
        self.swept.append(error)
        return 2

    @classmethod
    def reset(cls) -> None:
        cls.instances = []
        cls.run = None
        cls.questions = []
        cls.stored = []
        cls.recorded_rows = []
        cls.finished_rows = []


class FakeSearchService:
    def __init__(self, hits_by_query: dict[str, list[dict]] | None = None) -> None:
        self.hits_by_query = hits_by_query or {}
        self.calls: list[tuple[str, int]] = []
        self.error: Exception | None = None

    async def search(self, query: str, *, top_k: int | None = None) -> list[dict]:
        self.calls.append((query, top_k or 0))
        if self.error is not None:
            raise self.error
        return self.hits_by_query.get(query, [])


def _run(status: EvalRunStatus = EvalRunStatus.RUNNING) -> EvalRun:
    return EvalRun(
        id="run-1",
        testset_id="ts-1",
        status=status,
        config={"top_k": 3, "query_rewrite": False},
        metrics=None,
        error_message=None,
        created_at=CREATED_AT,
        finished_at=None,
        progress_done=0,
        progress_total=2,
    )


def _result(index: int, *, hit_rank: int | None, recall: int) -> EvalRunItem:
    return EvalRunItem(
        testset_item_id=f"item-{index}",
        query="旧结果",
        answer_document_id="doc-1",
        answer_chunk_index=index,
        hit_rank=hit_rank,
        recall=recall,
        latency_ms=20.0,
    )


def _question(index: int, query: str) -> EvalTestSetItem:
    return EvalTestSetItem(
        id=f"item-{index}",
        answer_document_id="doc-1",
        answer_chunk_index=index,
        status=EvalItemStatus.READY,
        query=query,
    )


def _make(
    *,
    run: EvalRun | None,
    questions: list[EvalTestSetItem],
    hits_by_query: dict[str, list[dict]] | None = None,
) -> tuple[EvalRunExecutor, FakeSearchService, FakeSessionFactory]:
    FakeEvalRepository.run = run
    FakeEvalRepository.questions = questions
    search = FakeSearchService(hits_by_query)
    factory = FakeSessionFactory()
    return EvalRunExecutor(session_factory=factory, search_service=search), search, factory


class ExecuteTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        FakeEvalRepository.reset()
        self._patcher = patch(
            "app.application.services.eval_run_executor.SqlAlchemyEvalRepository",
            FakeEvalRepository,
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    async def test_scores_every_question_then_finishes_with_aggregated_metrics(self) -> None:
        hits = {
            "苹果有什么营养？": [
                {"document_id": "doc-1", "chunk_index": 0},
                {"document_id": "doc-2", "chunk_index": 1},
            ],
            # 期望切片排在第 3，期望文档仍在 top-3 内
            "香蕉呢？": [
                {"document_id": "doc-2", "chunk_index": 0},
                {"document_id": "doc-2", "chunk_index": 5},
                {"document_id": "doc-1", "chunk_index": 1},
            ],
        }
        executor, search, factory = _make(
            run=_run(),
            questions=[_question(0, "苹果有什么营养？"), _question(1, "香蕉呢？")],
            hits_by_query=hits,
        )

        await executor.execute("run-1")

        self.assertEqual(
            [("苹果有什么营养？", 3), ("香蕉呢？", 3)],
            search.calls,  # k 取自 run 的配置快照，不是 settings.top_k
        )
        first, second = FakeEvalRepository.recorded_rows
        self.assertEqual(["item-0", "item-1"], [r.testset_item_id for r in (first, second)])
        self.assertEqual(1, first.hit_rank)
        self.assertEqual(1, first.recall)
        self.assertEqual(3, second.hit_rank)
        self.assertEqual(1, second.recall)
        for result in (first, second):
            self.assertGreaterEqual(result.latency_ms, 0)
            self.assertEqual(round(result.latency_ms, 1), result.latency_ms)
        # 一题一个事务，最后收尾再一次
        self.assertEqual(3, factory.session.commits)
        status, metrics, error = FakeEvalRepository.finished_rows[0]
        self.assertEqual(EvalRunStatus.DONE, status)
        self.assertIsNone(error)
        self.assertEqual(1.0, metrics["recall@3"])
        self.assertEqual(0.6667, metrics["mrr"])  # (1 + 1/3) / 2
        self.assertEqual(2, metrics["queries"])

    async def test_metrics_cover_every_stored_row_not_just_this_pass(self) -> None:
        """库里已有结果行（补跑场景）也得算进指标，不然 queries 会比实际行数少。"""

        FakeEvalRepository.stored = [_result(0, hit_rank=1, recall=1)]
        executor, _search, _factory = _make(run=_run(), questions=[])

        await executor.execute("run-1")

        _status, metrics, _error = FakeEvalRepository.finished_rows[0]
        self.assertEqual(1, metrics["queries"])
        self.assertEqual(1.0, metrics["recall@3"])
        self.assertEqual(1.0, metrics["mrr"])

    async def test_a_run_that_is_not_running_anymore_does_nothing(self) -> None:
        """已被启动扫标成 failed 的 run 不该再被跑一遍。"""

        executor, search, factory = _make(
            run=_run(EvalRunStatus.FAILED), questions=[_question(0, "x")]
        )

        await executor.execute("run-1")

        self.assertEqual([], search.calls)
        self.assertEqual(0, factory.session.commits)
        self.assertEqual([], FakeEvalRepository.finished_rows)

    async def test_a_vanished_run_does_nothing(self) -> None:
        executor, search, _factory = _make(run=None, questions=[_question(0, "x")])

        await executor.execute("run-1")

        self.assertEqual([], search.calls)
        self.assertEqual([], FakeEvalRepository.recorded_rows)
        self.assertEqual([], FakeEvalRepository.finished_rows)

    async def test_a_failed_search_fails_the_run_without_raising(self) -> None:
        """后台任务里抛出去只会在日志里留一行 Task exception，run 永远卡在 running。"""

        executor, search, factory = _make(
            run=_run(), questions=[_question(0, "苹果有什么营养？")]
        )
        search.error = RuntimeError("embedding down")

        await executor.execute("run-1")  # 不外抛

        self.assertEqual([], FakeEvalRepository.recorded_rows)
        status, metrics, error = FakeEvalRepository.finished_rows[0]
        self.assertEqual(EvalRunStatus.FAILED, status)
        self.assertIsNone(metrics)  # 没跑完就不给指标，免得半个数被当成整次的结论
        self.assertEqual("RuntimeError: embedding down", error)
        self.assertEqual(1, factory.session.commits)  # 只有收尾那一次

    async def test_start_runs_it_in_the_background(self) -> None:
        """start 不能等：POST 要立刻返回 run_id 给客户端轮询。"""

        executor, _search, factory = _make(
            run=_run(), questions=[_question(0, "苹果有什么营养？")]
        )

        executor.start("run-1")
        for _ in range(50):
            await asyncio.sleep(0)
            if FakeEvalRepository.finished_rows:
                break

        self.assertEqual(1, len(FakeEvalRepository.finished_rows))
        self.assertEqual(2, factory.session.commits)


class FailStaleRunsTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        FakeEvalRepository.reset()
        self._patcher = patch(
            "app.application.services.eval_run_executor.SqlAlchemyEvalRepository",
            FakeEvalRepository,
        )
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    async def test_marks_leftover_runs_failed_and_commits(self) -> None:
        """启动扫只需 PG：不碰 SearchService，也不该把向量库拉成启动前置条件。"""

        factory = FakeSessionFactory()

        await fail_stale_runs(factory)

        (repo,) = FakeEvalRepository.instances
        self.assertEqual([STALE_RUN_ERROR], repo.swept)
        self.assertEqual(1, factory.session.commits)


if __name__ == "__main__":
    unittest.main()
