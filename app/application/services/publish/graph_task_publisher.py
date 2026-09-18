"""图谱抽取任务发布者：graph_tasks 的 PENDING 投递到抽取队列（第四条链路）。"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.services.publish.base_publisher import BasePublisher
from app.config import GRAPH_TASK_POLICY, TaskPolicy
from app.infrastructure.postgres.graph_task_repository import SqlAlchemyGraphTaskRepository
from app.ports.task_queue import GraphTaskQueue

logger = logging.getLogger(__name__)


class GraphTaskPublisher(BasePublisher):
    """不停读 graph_tasks.pending -> 投递队列 -> 标 QUEUE。"""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker,
        queue: GraphTaskQueue,
        policy: TaskPolicy = GRAPH_TASK_POLICY,
    ) -> None:
        super().__init__(session_factory=session_factory, policy=policy)
        self._queue = queue

    async def publish_pending_once(self) -> int:
        """读取一批 PENDING 并投递，返回成功数量。"""

        published = 0
        async with self._session_factory() as session:
            tasks = SqlAlchemyGraphTaskRepository(session, retry_backoff_seconds=self._backoff)
            for entry in await tasks.list_pending(limit=self._batch_size):
                try:
                    await self._queue.enqueue(task_id=entry.id, document_id=entry.document_id)
                except Exception as exc:
                    await tasks.record_failure(entry.id, error=f"{type(exc).__name__}: {exc}")
                    if entry.attempts + 1 >= self._max_attempts:
                        await tasks.mark_failed(entry.id)
                        logger.error(
                            "抽取任务投递失败达到上限: task=%s doc=%s",
                            entry.id,
                            entry.document_id,
                        )
                    continue
                await tasks.mark_queued(entry.id)
                published += 1
            await session.commit()
        return published


__all__ = ["GraphTaskPublisher"]
