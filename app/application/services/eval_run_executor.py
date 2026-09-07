"""评测运行的执行器：进程内后台任务，逐题检索、打分、写结果。

为什么不走 Redis 队列（出题走）：出题要调 LLM 几百次、必须和 HTTP 请求解耦，
还要重试；run 只是把「一次 /search」换成「N 次 /search」，产物是一张结果表加
一段聚合指标，没有多进程要协调。检索侧的重活本来就在 API 进程里做，为它多开
一个消费者进程只是多一套部署。

代价是进程重启会打断正在跑的运行，所以启动时要把遗留的 running 收尾
（见模块底部的 fail_stale_runs）。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.services.search_service import SearchService
from app.domain.eval import EvalRun, EvalRunStatus, EvalTestSetItem
from app.domain.eval_metrics import aggregate, score_query
from app.infrastructure.eval_repository import SqlAlchemyEvalRepository

logger = logging.getLogger(__name__)

STALE_RUN_ERROR = "服务重启，运行被打断（结果只到中断前那一题）"


class EvalRunExecutor:
    """接手 EvalRunService 起好的 run，把它跑完。"""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker,
        search_service: SearchService,
    ) -> None:
        self._session_factory = session_factory
        self._search = search_service
        self._tasks: set[asyncio.Task] = set()

    def start(self, run_id: str) -> None:
        """起一个后台任务跑这个 run，不等它。

        task 的引用要留住：asyncio 只持弱引用，没人引用的任务可能被 GC 掉，
        表现得像 run 悄悄卡住。跑完由 done_callback 摘掉。
        """

        task = asyncio.create_task(self.execute(run_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def execute(self, run_id: str) -> None:
        """跑完一次评测，终态一定落库（除非进程中途被 cancel）。

        一题一个事务：轮询详情才看得到进度，中途挂掉也只丢当前这一题。
        聚合指标从库里已写出的结果行算，而不是从本次循环的内存结果算 —— 正常
        跑完时两者是同一批行，但读库让「metrics.queries == 结果行数」这个不变式
        不依赖执行路径，重入同一个 run 把剩下的题补完时也一样。
        """

        try:
            await self._run(run_id)
        except asyncio.CancelledError:
            # 关闭打断：这会儿提交也未必来得及，行留在 running，
            # 由下次启动的 fail_stale_runs 收尾。
            logger.warning("评测运行被打断: run=%s", run_id)
            raise
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            logger.exception("评测运行失败: run=%s", run_id)
            await self._finish(run_id, status=EvalRunStatus.FAILED, error=error)

    async def _run(self, run_id: str) -> None:
        run = await self._load(run_id)
        if run is None:
            return
        k = _top_k(run)
        for question in await self._questions(run_id):
            await self._score_one(run_id, question, k=k)

        metrics = await self._metrics(run_id, k=k)
        await self._finish(run_id, status=EvalRunStatus.DONE, metrics=metrics)
        logger.info("评测运行完成: run=%s metrics=%s", run_id, metrics)

    async def _load(self, run_id: str) -> EvalRun | None:
        async with self._session_factory() as session:
            run = await SqlAlchemyEvalRepository(session).get_run(run_id)
        if run is None:
            logger.error("评测运行不存在（测试集已删除？）: run=%s", run_id)
            return None
        if run.status is not EvalRunStatus.RUNNING:
            logger.warning(
                "评测运行已是终态，跳过: run=%s status=%s", run_id, run.status
            )
            return None
        return run

    async def _questions(self, run_id: str) -> list[EvalTestSetItem]:
        async with self._session_factory() as session:
            return await SqlAlchemyEvalRepository(
                session
            ).list_unscored_questions(run_id)

    async def _score_one(self, run_id: str, question: EvalTestSetItem, *, k: int) -> None:
        """问一次、打分、写一行结果。

        顺序跑而不是并发：avg_latency_ms 是给人看的数，几个 run 抢同一个
        embedding 服务时量出来的就是排队时间。
        """

        started = time.perf_counter()
        hits = await self._search.search(question.query or "", top_k=k)
        result = score_query(
            question,
            hits,
            k=k,
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        async with self._session_factory() as session:
            await SqlAlchemyEvalRepository(session).record_run_item(run_id, result)
            await session.commit()

    async def _metrics(self, run_id: str, *, k: int) -> dict[str, Any]:
        async with self._session_factory() as session:
            results = await SqlAlchemyEvalRepository(session).list_run_items(run_id)
        return aggregate(results, k=k)

    async def _finish(
        self,
        run_id: str,
        *,
        status: EvalRunStatus,
        metrics: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        async with self._session_factory() as session:
            await SqlAlchemyEvalRepository(session).finish_run(
                run_id, status=status, metrics=metrics, error_message=error
            )
            await session.commit()


async def fail_stale_runs(session_factory: async_sessionmaker) -> None:
    """启动时调用：把上一个进程遗留的 running 一律标成 failed。

    为什么不做成 EvalRunExecutor 的方法：收尾只需要 PG，不需要 SearchService
    那条链（它会把向量库的可用性也拉进启动前置条件）。没有租约或心跳可判，
    「进程里不会再有人跑它」这件事只有启动那一刻能确定。
    """

    async with session_factory() as session:
        count = await SqlAlchemyEvalRepository(session).fail_stale_runs(
            error=STALE_RUN_ERROR
        )
        await session.commit()
    if count:
        logger.warning("把上次遗留的评测运行标成失败: %d 个", count)


def _top_k(run: EvalRun) -> int:
    """run 自己的 k：写在配置快照里，不受事后改 .env 影响。"""

    return int(run.config["top_k"])


__all__ = ["STALE_RUN_ERROR", "EvalRunExecutor", "fail_stale_runs"]
