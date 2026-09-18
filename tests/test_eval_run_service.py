"""EvalRunService 用例测试（全 fake，不连 PG / Neo4j）。

run 的「跑」在 EvalRunConsumer 那边测，这里只测开跑前的判断与读：
什么不让跑（集不存在、没题、已经有一次在跑）、写进去的配置快照是什么、
以及开跑时按 ready 题 fan-out 了几条评测任务。
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase

from sqlalchemy.exc import IntegrityError

from app.application.services.evaluation.eval_run_service import EvalRunService
from app.domain.eval import (
    ChunkRef,
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
        status=status,
        query=query,
        evidence=[ChunkRef("doc-1", index)],
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
        config=(
        config
        if config is not None
        else {"top_k": 5, "query_rewrite": False, "graph": False}
    ),
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
        hit_rank=index + 1,
        latency_ms=10.0,
        evidence_total=2,
        evidence_matched=1,
        evidence_ranks=[index + 1],  # 两块该回一块回了：名次快照给 map 用
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

    async def reopen_run(self, run_id: str) -> None:
        run = self.runs.get(run_id)
        if run is not None and run.status is EvalRunStatus.FAILED:
            run.status = EvalRunStatus.RUNNING
            run.error_message = None
            run.finished_at = None


class FakeRunTaskRepository:
    """fan-out 的落点：start_run 每道 ready 题 add 一条 PENDING 任务。"""

    def __init__(self) -> None:
        self.added: list[tuple[str, str]] = []
        self.failed: dict[str, list[str]] = {}
        self.reset: list[str] = []

    async def add(self, *, run_id: str, item_id: str) -> None:
        self.added.append((run_id, item_id))

    async def reset_failed_for_run(self, run_id: str) -> int:
        ids = self.failed.pop(run_id, [])
        if ids:
            self.reset.append(run_id)
        return len(ids)


class FakeSearchService:
    def __init__(
        self, *, rewrite_enabled: bool = False, graph_enabled: bool = False
    ) -> None:
        self.rewrite_enabled = rewrite_enabled
        self.graph_enabled = graph_enabled


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
    run_tasks = FakeRunTaskRepository()
    service = EvalRunService(
        eval_repository=evals,  # testsets/items 侧
        run_repository=evals,  # run 侧：假件一身兼二职
        run_tasks=run_tasks,
        unit_of_work=uow,
        search_service=FakeSearchService(rewrite_enabled=rewrite_enabled),
        default_top_k=default_top_k,
    )
    return SimpleNamespace(service=service, evals=evals, uow=uow, run_tasks=run_tasks)


class StartRunTests(IsolatedAsyncioTestCase):
    async def test_creates_a_running_run_then_fans_out_one_task_per_question(self) -> None:
        ctx = _make()

        result = await ctx.service.start_run("ts-1")

        run_id = result["id"]
        self.assertEqual(
            [(run_id, "ts-1", {"top_k": 5, "query_rewrite": False, "graph": False})],
            ctx.evals.created,
        )
        self.assertEqual(1, ctx.uow.commits)
        # 两道 ready 题 -> 两条逐题任务，run 行与任务行同一个提交（发件箱的定义）
        self.assertEqual([(run_id, "item-0"), (run_id, "item-1")], ctx.run_tasks.added)
        self.assertEqual("running", result["status"])
        self.assertEqual(0, result["progress_done"])
        self.assertEqual(2, result["progress_total"])
        self.assertEqual([], result["items"])
        self.assertEqual(CREATED_AT.isoformat(), result["created_at"])

    async def test_records_the_retrieval_snapshot_of_this_run(self) -> None:
        """k 与「改写有没有接上」都要留在 run 上，否则两次 run 没法比。"""

        ctx = _make(rewrite_enabled=True)

        result = await ctx.service.start_run("ts-1", top_k=3)

        self.assertEqual(
            {"top_k": 3, "query_rewrite": True, "graph": False},
            result["config"],
        )

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
        self.assertEqual([], ctx.run_tasks.added)

    async def test_a_run_in_progress_blocks_a_second_one(self) -> None:
        """并行跑两个 run 会把排队时间算进 avg_latency_ms。"""

        ctx = _make()
        await ctx.service.start_run("ts-1")

        with self.assertRaises(ValueError) as exc:
            await ctx.service.start_run("ts-1")

        self.assertIn("已经有一次运行在跑", str(exc.exception))
        self.assertEqual(1, ctx.uow.commits)
        # 只有第一次 run 的 fan-out 落了任务，第二次被挡在提交之前
        self.assertEqual(2, len(ctx.run_tasks.added))

    async def test_losing_the_commit_race_reports_conflict(self) -> None:
        """_require_idle 的检查与提交之间有并发窗口：DB 部分唯一索引兜底时
        把 IntegrityError 翻译成 400（ValueError），run 与它的任务行一起回滚。"""

        class RacedUnitOfWork(FakeUnitOfWork):
            async def commit(self) -> None:
                raise IntegrityError(
                    "INSERT INTO eval_runs", {}, Exception("uq_eval_runs_running_per_testset")
                )

        ctx = _make(uow=RacedUnitOfWork())

        with self.assertRaises(ValueError) as exc:
            await ctx.service.start_run("ts-1")

        self.assertIn("已经有一次运行在跑", str(exc.exception))
        self.assertEqual(0, ctx.uow.commits)  # 提交失败：fan-out 的任务随事务回滚

    async def test_a_finished_run_does_not_block_the_next_one(self) -> None:
        ctx = _make()
        run_id = (await ctx.service.start_run("ts-1"))["id"]
        ctx.evals.runs[run_id].status = EvalRunStatus.DONE

        second_run_id = (await ctx.service.start_run("ts-1"))["id"]

        # 两次 run 各自 fan-out 一整套任务，run_id 不同互不串
        self.assertEqual(4, len(ctx.run_tasks.added))
        self.assertEqual({run_id, second_run_id}, {rid for rid, _ in ctx.run_tasks.added})

    async def test_unknown_testset_raises_keyerror_without_starting(self) -> None:
        ctx = _make()

        with self.assertRaises(KeyError):
            await ctx.service.start_run("ghost")

        self.assertEqual(0, ctx.uow.commits)
        self.assertEqual([], ctx.run_tasks.added)


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
                    "hit_rank": 1,
                    "evidence_ranks": [1],
                    "recall": 0,  # 块级全在：2 块该回 1 块，不给过
                    "map": 0.5,
                    "latency_ms": 10.0,
                    "evidence_total": 2,
                    "evidence_matched": 1,
                    "evidence_coverage": 0.5,
                },
                {
                    "testset_item_id": "item-1",
                    "query": "豆腐有多少蛋白质？",
                    "hit_rank": 2,
                    "evidence_ranks": [2],
                    "recall": 0,
                    "map": 0.25,
                    "latency_ms": 10.0,
                    "evidence_total": 2,
                    "evidence_matched": 1,
                    "evidence_coverage": 0.5,
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


class RerunFailedTests(IsolatedAsyncioTestCase):
    async def _failed_run(self, *, with_failed_task: bool = True):
        ctx = _make()
        created = await ctx.service.start_run("ts-1")
        run_id = created["id"]
        ctx.evals.runs[run_id].status = EvalRunStatus.FAILED
        if with_failed_task:
            ctx.run_tasks.failed[run_id] = ["task-1"]
        return ctx, run_id

    async def test_rerun_resets_tasks_reopens_run_and_commits(self) -> None:
        ctx, run_id = await self._failed_run()
        commits_before = ctx.uow.commits

        result = await ctx.service.rerun_failed(run_id)

        self.assertEqual("running", result["status"])
        self.assertEqual([run_id], ctx.run_tasks.reset)
        self.assertEqual(commits_before + 1, ctx.uow.commits)

    async def test_only_failed_runs_can_be_rerun(self) -> None:
        ctx = _make()
        created = await ctx.service.start_run("ts-1")

        with self.assertRaises(ValueError):
            await ctx.service.rerun_failed(created["id"])  # 还在 running

    async def test_rerun_without_failed_tasks_is_rejected(self) -> None:
        ctx, run_id = await self._failed_run(with_failed_task=False)
        commits_before = ctx.uow.commits

        with self.assertRaises(ValueError):
            await ctx.service.rerun_failed(run_id)
        self.assertEqual(commits_before, ctx.uow.commits)

    async def test_unknown_run_raises_keyerror(self) -> None:
        ctx = _make()
        with self.assertRaises(KeyError):
            await ctx.service.rerun_failed("nope")


if __name__ == "__main__":
    unittest.main()
