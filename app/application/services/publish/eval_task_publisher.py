"""出题任务发布者：把 eval_tasks 的 PENDING 任务投递到 Eval Stream。

与 DocumentTaskPublisher 共用 BasePublisher 的轮询循环，差异：
- 数据源是 eval_tasks（每个 item 唯一任务）；
- list_pending 使用 FOR UPDATE SKIP LOCKED，支持多个 publisher 并发领取；
- 轮询间隔 / 批量 / 重试上限独立配置（LLM 失败率高于索引，节奏放宽）；
- 投递超限要连同条目一起收尾，否则测试集永远停在 generating。
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.services.publish.base_publisher import BasePublisher
from app.infrastructure.eval_repository import SqlAlchemyEvalRepository
from app.infrastructure.eval_task_repository import SqlAlchemyEvalTaskRepository
from app.ports.task_queue import EvalTaskQueue
from settings import settings

logger = logging.getLogger(__name__)


class EvalTaskPublisher(BasePublisher):
    """不停读 eval_tasks.pending -> 投递队列 -> 标 QUEUE。"""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker,
        queue: EvalTaskQueue,
    ) -> None:
        super().__init__(
            session_factory=session_factory,
            interval_seconds=settings.eval_task_publish_interval_seconds,
            batch_size=settings.eval_task_publish_batch_size,
            max_attempts=settings.eval_task_max_attempts,
        )
        self._queue = queue

    async def publish_pending_once(self) -> int:
        """领取一批 PENDING 并投递，返回成功数量。"""

        published = 0
        async with self._session_factory() as session:
            tasks = SqlAlchemyEvalTaskRepository(session)
            evals = SqlAlchemyEvalRepository(session)
            for entry in await tasks.list_pending(limit=self._batch_size):
                published += await self._publish_one(entry, tasks, evals)
            await session.commit()
        return published

    async def _publish_one(
        self,
        entry,
        tasks: SqlAlchemyEvalTaskRepository,
        evals: SqlAlchemyEvalRepository,
    ) -> int:
        """投递单条任务。"""

        try:
            await self._queue.enqueue(task_id=entry.id, item_id=entry.item_id)
        except Exception as exc:
            await tasks.record_failure(entry.id, error=f"{type(exc).__name__}: {exc}")
            if entry.attempts + 1 >= self._max_attempts:
                await tasks.mark_failed(entry.id)
                # 任务终态就得把条目一起收尾，否则测试集永远等在 generating
                await evals.set_item_failed(entry.item_id, error="任务投递失败达到上限")
                await evals.finalize_testset(entry.testset_id)
                logger.error("出题任务投递失败达到上限: task=%s item=%s", entry.id, entry.item_id)
            return 0
        await tasks.mark_queued(entry.id)
        return 1


__all__ = ["EvalTaskPublisher"]
