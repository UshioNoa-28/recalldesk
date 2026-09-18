"""逐题评测任务发布者：把 eval_run_tasks 的 PENDING 投递到 Eval Run Stream。

与出题的 EvalTaskPublisher 共用 BasePublisher 轮询循环，差异只在收尾：
投递超限把任务标 FAILED 后，必须试一次 finalize_run —— 否则「最后一题」恰恰
投递失败时，run 会因为数不到在途任务而永远停在 running。
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.services.publish.base_publisher import BasePublisher
from app.config import EVAL_RUN_TASK_POLICY, TaskPolicy
from app.domain.eval import EvalRunTask
from app.infrastructure.postgres.eval_repository import SqlAlchemyEvalRepository
from app.infrastructure.postgres.eval_run_task_repository import SqlAlchemyEvalRunTaskRepository
from app.ports.task_queue import EvalRunTaskQueue

logger = logging.getLogger(__name__)


class EvalRunTaskPublisher(BasePublisher):
    """不停读 eval_run_tasks.pending -> 投递队列 -> 标 QUEUE。"""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker,
        queue: EvalRunTaskQueue,
        policy: TaskPolicy = EVAL_RUN_TASK_POLICY,
    ) -> None:
        super().__init__(session_factory=session_factory, policy=policy)
        self._queue = queue

    async def publish_pending_once(self) -> int:
        """领取一批 PENDING 并投递，返回成功数量。"""

        published = 0
        async with self._session_factory() as session:
            tasks = SqlAlchemyEvalRunTaskRepository(session, retry_backoff_seconds=self._backoff)
            evals = SqlAlchemyEvalRepository(session)
            for entry in await tasks.list_pending(limit=self._batch_size):
                published += await self._publish_one(entry, tasks, evals)
            await session.commit()
        return published

    async def _publish_one(
        self,
        entry: EvalRunTask,
        tasks: SqlAlchemyEvalRunTaskRepository,
        evals: SqlAlchemyEvalRepository,
    ) -> int:
        """投递单条任务：成功标 QUEUE，失败退避，超限终态并收尾 run。"""

        try:
            await self._queue.enqueue(
                task_id=entry.id, run_id=entry.run_id, item_id=entry.item_id
            )
        except Exception as exc:
            await tasks.record_failure(entry.id, error=f"{type(exc).__name__}: {exc}")
            if entry.attempts + 1 >= self._max_attempts:
                await tasks.mark_failed(entry.id)
                # 收尾要拿最新的全局计数：本次刚标的 FAILED 行在同一事务里可见
                counts = await tasks.count_by_status(entry.run_id)
                await evals.finalize_run(
                    entry.run_id,
                    pending_open=counts.get("pending", 0) + counts.get("queue", 0),
                    failed=counts.get("failed", 0),
                )
                logger.error(
                    "评测任务投递失败达到上限: task=%s run=%s item=%s",
                    entry.id,
                    entry.run_id,
                    entry.item_id,
                )
            return 0
        await tasks.mark_queued(entry.id)
        return 1


__all__ = ["EvalRunTaskPublisher"]
