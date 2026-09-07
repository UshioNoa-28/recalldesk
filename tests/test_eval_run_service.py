"""EvalRunService 用例测试（全 fake，不连 PG / Qdrant）。

run 的「跑」在 EvalRunExecutor 那边测，这里只测开跑前的判断与读：
什么不让跑（集不存在、没题、已经有一次在跑）、写进去的配置快照是什么、
以及起了任务之后返回什么。
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

from sqlalchemy.exc import IntegrityError

from app.application.services.eval_run_service import EvalRunService
from app.domain.eval import (
    EvalItemStatus,
    EvalRun,
    EvalRunItem,
    EvalRunStatus,
    EvalTestSet,
    EvalTestSetItem,
    TestSetStatus,
)

CREATED_AT = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


def _testset(testset_id: str = "ts-1") -> EvalTestSet:
    return EvalTestSet(
        id=testset_id,
        name="水果题集",
        status=TestSetStatus.READY,
        progress_done=2,
        progress_total=2,
        error_message=None,
        created_at=CREATED_AT,
    )


def _item(
    index: int,
    *,
    status: EvalItemStatus = EvalItemStatus.READY,
    query: str | None = "豆腐有多少蛋白质？",
) -> EvalTestSetItem:
    return EvalTestSetItem(
        id=f"item-{index}",
        answer_document_id="doc-1",
        answer_chunk_index=index,
        status=status,
        query=query,
    )


def _run(
    run_id: str,
    *,
    status: EvalRunStatus,
    testset_id: str = "ts-1",
    config: dict | None = None,
) -> EvalRun:
    return EvalRun(
        id=run_id,
        testset_id=testset_id,
        status=status,
        config=config if config is not None else {"top_k": 5, "query_rewrite": False},
        metrics=None,
        error_message=None,
        created_at=CREATED_AT,
        finished_at=None,
        progress_done=0,
        progress_total=2,
    )


def _result(index: int) -> EvalRunItem:
    return EvalRunItem(
        testset_item_id=f"item-{index}",
        query="豆腐有多少蛋白质？",
        answer_document_id="doc-1",
        answer_chunk_index=index,
        hit_rank=index + 1,
        recall=1,
        latency_ms=10.0,
    )


class FakeEvalRepository:
    def __init__(self, *, items: list[EvalTestSetItem] | None = None) -> None:
        self.testsets = {"ts-1": _testset()}
        self.items = items if items is not None else [_item(0), _item(1)]
        self.runs: dict[str, EvalRun] = {}
        self.results: dict[str, list[EvalRunItem]] = {}
        self.created: list[tuple[str, str, dict]] = []

    async def get_testset(self, testset_id: str) -> EvalTestSet | None:
        return self.testsets.get(testset_id)

    async def list_testset_items(self, testset_id: str) -> list[EvalTestSetItem]:
        return self.items

    async def create_run(
        self, *, run_id: str, testset_id: str, config: dict
    ) -> None:
        self.created.append((run_id, testset_id, config))
        self.runs[run_id] = _run(
            run_id,
            status=EvalRunStatus.RUNNING,
            testset_id=testset_id,
            config=config,
        )
        self.results[run_id] = []

    async def get_run(self, run_id: str) -> EvalRun | None:
        run = self.runs.get(run_id)
        if run is None:
            return None
        run.progress_done = len(self.results.get(run_id, []))
        run.progress_total = len(
            [item for item in self.items if item.status is EvalItemStatus.READY]
        )
        return run

    async def list_runs(self, testset_id: str) -> list[EvalRun]:
        return [run for run in self.runs.values() if run.testset_id == testset_id]

    async def list_run_items(self, run_id: str) -> list[EvalRunItem]:
        return self.results.get(run_id, [])


class FakeExecutor:
    """只记 start 的参数：真执行是另一个测试文件的事。"""

    def __init__(self) -> None:
        self.started: list[str] = []

    def start(self, run_id: str) -> None:
        self.started.append(run_id)


class FakeSearchService:
    def __init__(self, *, rewrite_enabled: bool = False) -> None:
        self.rewrite_enabled = rewrite_enabled


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


def _make(
    *,
    items: list[EvalTestSetItem] | None = None,
    rewrite_enabled: bool = False,
    default_top_k: int = 5,
    uow: FakeUnitOfWork | None = None,
) -> SimpleNamespace:
    evals = FakeEvalRepository(items=items)
    uow = uow or FakeUnitOfWork()
    executor = FakeExecutor()
    service = EvalRunService(
        eval_repository=evals,
        unit_of_work=uow,
        executor=executor,
        search_service=FakeSearchService(rewrite_enabled=rewrite_enabled),
        default_top_k=default_top_k,
    )
    return SimpleNamespace(service=service, evals=evals, uow=uow, executor=executor)


class StartRunTests(IsolatedAsyncioTestCase):
    async def test_creates_a_running_run_then_hands_it_to_the_executor(self) -> None:
        ctx = _make()

        result = await ctx.service.start_run("ts-1")

        run_id = result["id"]
        self.assertEqual(
            [(run_id, "ts-1", {"top_k": 5, "query_rewrite": False})],
            ctx.evals.created,
        )
        self.assertEqual(1, ctx.uow.commits)
        self.assertEqual([run_id], ctx.executor.started)
        self.assertEqual("running", result["status"])
        self.assertEqual(0, result["progress_done"])
        self.assertEqual(2, result["progress_total"])
        self.assertEqual([], result["items"])
        self.assertEqual(CREATED_AT.isoformat(), result["created_at"])

    async def test_records_the_retrieval_snapshot_of_this_run(self) -> None:
        """k 与「改写有没有接上」都要留在 run 上，否则两次 run 没法比。"""

        ctx = _make(rewrite_enabled=True)

        result = await ctx.service.start_run("ts-1", top_k=3)

        self.assertEqual({"top_k": 3, "query_rewrite": True}, result["config"])

    async def test_default_top_k_applies_when_the_request_omits_it(self) -> None:
        ctx = _make(default_top_k=8)

        result = await ctx.service.start_run("ts-1", top_k=None)

        self.assertEqual(8, result["config"]["top_k"])

    async def test_only_ready_questions_count_as_something_to_run(self) -> None:
        """还在 generating 的集也能跑，跑的是已经出好的那部分。"""

        ctx = _make(
            items=[
                _item(0),
                _item(1, status=EvalItemStatus.PENDING, query=None),
                _item(2, status=EvalItemStatus.FAILED, query=None),
            ]
        )

        result = await ctx.service.start_run("ts-1")

        self.assertEqual(1, result["progress_total"])
        self.assertEqual(1, ctx.uow.commits)

    async def test_a_testset_without_ready_questions_cannot_be_run(self) -> None:
        """空 run 会给出 recall@k = 0，那是个假数字而不是「检索很差」。"""

        ctx = _make(items=[_item(0, status=EvalItemStatus.PENDING, query=None)])

        with self.assertRaises(ValueError) as exc:
            await ctx.service.start_run("ts-1")

        self.assertIn("生成好", str(exc.exception))
        self.assertEqual(0, ctx.uow.commits)
        self.assertEqual([], ctx.executor.started)

    async def test_a_run_in_progress_blocks_a_second_one(self) -> None:
        """并行跑两个 run 会把排队时间算进 avg_latency_ms。"""

        ctx = _make()
        await ctx.service.start_run("ts-1")

        with self.assertRaises(ValueError) as exc:
            await ctx.service.start_run("ts-1")

        self.assertIn("已经有一次运行在跑", str(exc.exception))
        self.assertEqual(1, ctx.uow.commits)
        self.assertEqual(1, len(ctx.executor.started))

    async def test_losing_the_commit_race_reports_conflict(self) -> None:
        """_require_idle 的检查与提交之间有并发窗口：DB 部分唯一索引兜底时
        把 IntegrityError 翻译成 400（ValueError），且不把 run 交给执行器。"""

        class RacedUnitOfWork(FakeUnitOfWork):
            async def commit(self) -> None:
                raise IntegrityError(
                    "INSERT INTO eval_runs", {}, Exception("uq_eval_runs_running_per_testset")
                )

        ctx = _make(uow=RacedUnitOfWork())

        with self.assertRaises(ValueError) as exc:
            await ctx.service.start_run("ts-1")

        self.assertIn("已经有一次运行在跑", str(exc.exception))
        self.assertEqual([], ctx.executor.started)

    async def test_a_finished_run_does_not_block_the_next_one(self) -> None:
        ctx = _make()
        run_id = (await ctx.service.start_run("ts-1"))["id"]
        ctx.evals.runs[run_id].status = EvalRunStatus.DONE

        await ctx.service.start_run("ts-1")

        self.assertEqual(2, len(ctx.executor.started))

    async def test_unknown_testset_raises_keyerror_without_starting(self) -> None:
        ctx = _make()

        with self.assertRaises(KeyError):
            await ctx.service.start_run("ghost")

        self.assertEqual(0, ctx.uow.commits)
        self.assertEqual([], ctx.executor.started)


class ReadRunTests(IsolatedAsyncioTestCase):
    async def test_get_run_returns_the_detail_with_results(self) -> None:
        ctx = _make()
        run_id = (await ctx.service.start_run("ts-1"))["id"]
        ctx.evals.results[run_id] = [_result(0), _result(1)]
        ctx.evals.runs[run_id].status = EvalRunStatus.DONE
        ctx.evals.runs[run_id].metrics = {"recall@5": 1.0, "queries": 2}

        detail = await ctx.service.get_run(run_id)

        self.assertEqual(2, detail["progress_done"])
        self.assertEqual("done", detail["status"])
        self.assertEqual({"recall@5": 1.0, "queries": 2}, detail["metrics"])
        self.assertEqual(
            [
                {
                    "testset_item_id": "item-0",
                    "query": "豆腐有多少蛋白质？",
                    "answer_document_id": "doc-1",
                    "answer_chunk_index": 0,
                    "hit_rank": 1,
                    "recall": 1,
                    "mrr": 1.0,
                    "low_recall": False,
                    "latency_ms": 10.0,
                },
                {
                    "testset_item_id": "item-1",
                    "query": "豆腐有多少蛋白质？",
                    "answer_document_id": "doc-1",
                    "answer_chunk_index": 1,
                    "hit_rank": 2,
                    "recall": 1,
                    "mrr": 0.5,
                    "low_recall": False,
                    "latency_ms": 10.0,
                },
            ],
            detail["items"],
        )

    async def test_unknown_run_raises_keyerror(self) -> None:
        ctx = _make()

        with self.assertRaises(KeyError):
            await ctx.service.get_run("ghost")

    async def test_list_runs_returns_summaries_for_the_testset(self) -> None:
        ctx = _make()
        run_id = (await ctx.service.start_run("ts-1"))["id"]

        result = await ctx.service.list_runs("ts-1")

        self.assertEqual([run_id], [run["id"] for run in result["runs"]])
        self.assertNotIn("items", result["runs"][0])

    async def test_list_runs_of_an_unknown_testset_raises_keyerror(self) -> None:
        ctx = _make()

        with self.assertRaises(KeyError):
            await ctx.service.list_runs("ghost")


if __name__ == "__main__":
    unittest.main()
