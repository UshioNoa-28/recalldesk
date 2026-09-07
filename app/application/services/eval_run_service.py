"""评测运行的用例编排：起一个 run、看进度、看结果。

执行交给 EvalRunExecutor（进程内后台任务），这里只做开跑前的判断和读：
POST 立刻返回 run_id，客户端轮询详情接口看 progress_done / status。
"""

from __future__ import annotations

import uuid

from sqlalchemy.exc import IntegrityError

from app.application.services.eval_run_executor import EvalRunExecutor
from app.application.services.search_service import SearchService
from app.domain.eval import EvalItemStatus, EvalRun, EvalRunItem, EvalRunStatus
from app.ports.eval_repository import EvalRepository
from app.ports.unit_of_work import UnitOfWork


class EvalRunService:
    """run 的用例编排。"""

    def __init__(
        self,
        *,
        eval_repository: EvalRepository,
        unit_of_work: UnitOfWork,
        executor: EvalRunExecutor,
        search_service: SearchService,
        default_top_k: int,
    ) -> None:
        self._evals = eval_repository
        self._unit_of_work = unit_of_work
        self._executor = executor
        self._search = search_service
        self._default_top_k = default_top_k

    async def start_run(self, testset_id: str, *, top_k: int | None = None) -> dict:
        """开一次评测：判断 → 写 running 行 → 提交 → 交给后台执行器。

        跑的是「此刻已经出好的题」：测试集还在 generating 也可以跑，只是分母
        只数 ready 的那些。一道 ready 题都没有就不让跑 —— 空评测会给出
        recall@k = 0，那是个假数字而不是「检索很差」。
        """

        if await self._evals.get_testset(testset_id) is None:
            raise KeyError(testset_id)
        await self._require_idle(testset_id)

        k = top_k or self._default_top_k
        ready = [
            item
            for item in await self._evals.list_testset_items(testset_id)
            # ready 隐含 query 非空，这里两个条件是一回事：写下它们是说明
            # 「跑的是已出好的题」而不是「跑全部题目」
            if item.status is EvalItemStatus.READY and item.query
        ]
        if not ready:
            raise ValueError("评测集里还没有生成好的题目，先把题出完再跑")

        run_id = str(uuid.uuid4())
        await self._evals.create_run(
            run_id=run_id,
            testset_id=testset_id,
            # 配置快照：k 决定 recall@k 的口径，改写决定检索走了几条路。
            # 事后改 .env 不影响已开跑的 run，两次 run 之间也才可比。
            config={"top_k": k, "query_rewrite": self._search.rewrite_enabled},
        )
        try:
            await self._unit_of_work.commit()
        except IntegrityError as exc:
            # _require_idle 的「查 running 再插入」之间有并发窗口，DB 里的
            # 部分唯一索引（一个测试集最多一个 running）是最终防线；
            # 在这里把冲突翻译成 400 给前端
            raise ValueError(
                "这个评测集已经有一次运行在跑，等它结束再开新的"
            ) from exc
        # 先提交再起任务：执行器用的是另一个 session，看不见未提交的行
        self._executor.start(run_id)
        return await self.get_run(run_id)

    async def get_run(self, run_id: str) -> dict:
        """运行详情：状态 + 进度 + 聚合指标 + 逐题结果；不存在抛 KeyError。"""

        run = await self._evals.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        items = await self._evals.list_run_items(run_id)
        return {**_run_dict(run), "items": [_run_item_dict(item) for item in items]}

    async def list_runs(self, testset_id: str) -> dict:
        """某测试集的历史运行（不含逐题结果），按创建时间降序。"""

        if await self._evals.get_testset(testset_id) is None:
            raise KeyError(testset_id)
        runs = await self._evals.list_runs(testset_id)
        return {"runs": [_run_dict(run) for run in runs]}

    async def _require_idle(self, testset_id: str) -> None:
        """同一个测试集同时只让跑一个 run。

        不是为了数据（各 run 的结果行互不干扰），是为了量出来的延迟准：
        两个 run 并行就是把 embedding 服务的排队时间算进 avg_latency_ms。
        这里的检查只是给用户友好的报错和进度，真正的原子性由
        eval_runs 上的部分唯一索引兜底（并发窗口里撞索引会走 ValueError）。
        """

        running = [
            run
            for run in await self._evals.list_runs(testset_id)
            if run.status is EvalRunStatus.RUNNING
        ]
        if running:
            first = running[0]
            raise ValueError(
                "这个评测集已经有一次运行在跑"
                f"（{first.progress_done}/{first.progress_total}），等它结束再开新的"
            )


def _run_dict(run: EvalRun) -> dict:
    return {
        "id": run.id,
        "testset_id": run.testset_id,
        "status": run.status.value,
        "config": run.config,
        "metrics": run.metrics,
        "error_message": run.error_message,
        "progress_done": run.progress_done,
        "progress_total": run.progress_total,
        "created_at": run.created_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


def _run_item_dict(item: EvalRunItem) -> dict:
    """逐题结果：mrr / low_recall 是派生的，也一并给出去省得前端再算一遍口径。"""

    return {
        "testset_item_id": item.testset_item_id,
        "query": item.query,
        "answer_document_id": item.answer_document_id,
        "answer_chunk_index": item.answer_chunk_index,
        "hit_rank": item.hit_rank,
        "recall": item.recall,
        "mrr": item.mrr,
        "low_recall": item.low_recall,
        "latency_ms": item.latency_ms,
    }


__all__ = ["EvalRunService"]
