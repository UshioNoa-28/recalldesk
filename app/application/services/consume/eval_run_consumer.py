"""逐题评测消费者：从 Eval Run Stream 领任务，检索一次、打分一行、落定后收尾。

设计说明（与出题消费者 EvalQuestionConsumer 同一族规，消费循环 / ACK 规则
见 BaseConsumer）：
- APP 作用域后台循环，注入 session_factory 自管短事务；
  一次任务两段事务：领取校验（短）→ 检索（慢 I/O，不占 DB 连接）→ 回写（短）；
- 重投安全靠幂等：任务已终态跳过、结果行已存在跳过（has_run_result）；
- run 不再是「一个进程的循环」：每行 run_items 落库进度就 +1（进度是数出来的），
  聚合指标与收尾由 finalize_run 在「该 run 无在途任务」时做一次，谁最后谁收尾；
- 检索失败：attempts+1、任务回 PENDING（指数退避由 publisher 重投），超限任务
  标 FAILED 并触发 finalize —— run 收成 failed 而不是永远挂着；
- 题目在 run 期间被重置（retry_failed_items 清掉 query）或消失：重试变不出题面，
  按永久失败处理，同样走 finalize。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.services.consume.base_consumer import BaseConsumer
from app.application.services.search.search_service import SearchService
from app.config import EVAL_RUN_TASK_POLICY, TaskPolicy
from app.domain.eval import EvalRunStatus, EvalTaskStatus
from app.domain.eval_metrics import score_query
from app.infrastructure.postgres.eval_repository import SqlAlchemyEvalRepository
from app.infrastructure.postgres.eval_run_repository import SqlAlchemyEvalRunRepository
from app.infrastructure.postgres.eval_run_task_repository import SqlAlchemyEvalRunTaskRepository
from app.ports.task_queue import EvalRunTaskQueue

logger = logging.getLogger(__name__)


class EvalRunConsumer(BaseConsumer):
    """不停消费逐题评测任务：一题一次检索一个结果行。"""

    consumer_name_prefix = "eval-run-consumer"

    def __init__(
        self,
        *,
        queue: EvalRunTaskQueue,
        session_factory: async_sessionmaker,
        search_service: SearchService,
        consumer_name: str | None = None,
        policy: TaskPolicy = EVAL_RUN_TASK_POLICY,
    ) -> None:
        super().__init__(
            queue=queue,
            session_factory=session_factory,
            policy=policy,
            consumer_name=consumer_name,
        )
        self._search = search_service

    def _extract_task_ids(self, data: dict[str, Any]) -> dict[str, str] | None:
        task_id = data.get("task_id")
        run_id = data.get("run_id")
        item_id = data.get("item_id")
        if not task_id or not run_id or not item_id:
            return None
        return {"task_id": task_id, "run_id": run_id, "item_id": item_id}

    async def _handle_task(self, *, task_id: str, run_id: str, item_id: str) -> None:
        """跑一题：领取校验 -> 检索 -> 回写落定。业务失败落库后正常返回。"""

        # ---- 领取事务：校验 + 取料，慢 I/O 之前把连接还给池 ----
        async with self._session_factory() as session:
            tasks = SqlAlchemyEvalRunTaskRepository(session, retry_backoff_seconds=self._backoff)
            evals = SqlAlchemyEvalRunRepository(session)
            catalog = SqlAlchemyEvalRepository(session)

            task = await tasks.get(task_id)
            if task is None:
                # 任务行没了（run 或题目被级联删）：这条消息就是它存在的最后痕迹。
                # 试着收尾一次 —— 如果它是最后一条在途的，run 不该继续挂着。
                await self._finalize(evals, tasks, run_id)
                await session.commit()
                return
            if task.status in (EvalTaskStatus.SUCCESS, EvalTaskStatus.FAILED):
                return  # 幂等：redelivery，上一手已经把回写和收尾一起提交了

            run = await evals.get_run(run_id)
            if run is None or run.status is not EvalRunStatus.RUNNING:
                await tasks.mark_success(task_id)  # 无事可做也算消费掉
                await session.commit()
                return
            if await evals.has_run_result(run_id, item_id):
                # 结果行在而任务没落定：上一手提交到一半崩了。补记 + 收尾，不再检索。
                await tasks.mark_success(task_id)
                await self._finalize(evals, tasks, run_id)
                await session.commit()
                return

            item = await catalog.get_item(item_id)
            if item is None or not item.query:
                # 题面没了（run 期间被重置/重出）：重试变不出题面，直接终态
                await tasks.record_failure(task_id, error="题目无题面（被重置或已删除）")
                await tasks.mark_failed(task_id)
                await self._finalize(evals, tasks, run_id)
                await session.commit()
                logger.error("题目缺题面，任务终态失败: task=%s item=%s", task_id, item_id)
                return

            k = int(run.config["top_k"])
            query = item.query

        # ---- 慢 I/O：一次检索，不占 DB 连接（顺序与延迟口径见「一题一事务」的理由）----
        try:
            started = time.perf_counter()
            hits = await self._search.search(query, top_k=k)
            result = score_query(
                item,
                hits,
                k=k,
                latency_ms=round((time.perf_counter() - started) * 1000, 1),
            )
        except Exception as exc:
            await self._record_search_failure(task_id, run_id, exc)
            return

        # ---- 回写事务：一题一行一提交，轮询详情才看得到进度 ----
        async with self._session_factory() as session:
            tasks = SqlAlchemyEvalRunTaskRepository(session, retry_backoff_seconds=self._backoff)
            evals = SqlAlchemyEvalRunRepository(session)
            await evals.record_run_item(run_id, result)
            await tasks.mark_success(task_id)
            await self._finalize(evals, tasks, run_id)
            await session.commit()

    async def _record_search_failure(
        self, task_id: str, run_id: str, exc: Exception
    ) -> None:
        """检索失败：退避重投，超限终态 + 收尾。"""

        error = f"{type(exc).__name__}: {exc}"
        async with self._session_factory() as session:
            tasks = SqlAlchemyEvalRunTaskRepository(session, retry_backoff_seconds=self._backoff)
            evals = SqlAlchemyEvalRunRepository(session)
            await tasks.record_failure(task_id, error=error)
            refreshed = await tasks.get(task_id)
            if refreshed is not None and refreshed.attempts >= self._policy.max_attempts:
                await tasks.mark_failed(task_id)
                await self._finalize(evals, tasks, run_id)
                logger.error(
                    "评测任务失败达到上限: task=%s run=%s error=%s", task_id, run_id, error
                )
            else:
                logger.warning(
                    "评测任务失败（未超限，回 PENDING 等重投）: task=%s error=%s",
                    task_id,
                    error,
                )
            await session.commit()

    async def _finalize(
        self,
        evals: SqlAlchemyEvalRunRepository,
        tasks: SqlAlchemyEvalRunTaskRepository,
        run_id: str,
    ) -> None:
        """数任务 -> 落定则收尾。同事务内自己刚标的状态对自己可见（autoflush）。"""

        counts = await tasks.count_by_status(run_id)
        await evals.finalize_run(
            run_id,
            pending_open=counts.get("pending", 0) + counts.get("queue", 0),
            failed=counts.get("failed", 0),
        )


__all__ = ["EvalRunConsumer"]
