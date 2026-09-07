"""任务发布者：把 document_tasks 的 PENDING 任务投递到文档索引队列。

APP 作用域后台循环，注入 session_factory 自管短事务。
轮询循环在 BasePublisher，这里只回答「领哪张表、往哪条队列投」。
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.services.publish.base_publisher import BasePublisher
from app.infrastructure.document_task_repository import SqlAlchemyDocumentTaskRepository
from app.ports.task_queue import DocumentTaskQueue
from settings import settings

logger = logging.getLogger(__name__)


class DocumentTaskPublisher(BasePublisher):
    """不停读 document_tasks.pending -> 投递队列 -> 标 QUEUE。"""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker,
        queue: DocumentTaskQueue,
    ) -> None:
        super().__init__(
            session_factory=session_factory,
            interval_seconds=settings.task_publish_interval_seconds,
            batch_size=settings.task_publish_batch_size,
            max_attempts=settings.task_max_attempts,
        )
        self._queue = queue

    async def publish_pending_once(self) -> int:
        """读取一批 PENDING 并投递，返回成功数量。"""

        published = 0
        async with self._session_factory() as session:
            outbox = SqlAlchemyDocumentTaskRepository(session)
            entries = await outbox.list_pending(limit=self._batch_size)
            for entry in entries:
                published += await self._publish_one(entry, outbox)
            await session.commit()
        return published

    async def _publish_one(self, entry, outbox: SqlAlchemyDocumentTaskRepository) -> int:
        """投递单条任务。"""

        try:
            await self._queue.enqueue(
                task_id=entry.id,
                document_id=entry.document_id,
                operation=entry.operation,
            )
        except Exception as exc:
            await outbox.record_failure(entry.id, error=f"{type(exc).__name__}: {exc}")
            if entry.attempts + 1 >= self._max_attempts:
                await outbox.mark_failed(entry.id)
                logger.error("任务投递失败达到上限: task=%s doc=%s", entry.id, entry.document_id)
            return 0
        await outbox.mark_queued(entry.id)
        return 1


__all__ = ["DocumentTaskPublisher"]
