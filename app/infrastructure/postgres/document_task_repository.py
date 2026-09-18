"""document_tasks 表（Transactional Outbox）的 SQLAlchemy 实现。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.documents import DocumentTask, DocumentTaskStatus
from app.infrastructure.postgres.tables import DocumentTaskTable
from app.ports.persistence.document_task_repository import DocumentTaskRepository


class SqlAlchemyDocumentTaskRepository(DocumentTaskRepository):
    """在调用方提供的 Session 中读写 document_tasks 表。"""

    def __init__(self, session: AsyncSession, *, retry_backoff_seconds: float = 30.0) -> None:
        self._session = session
        self._retry_backoff_seconds = retry_backoff_seconds

    async def add(self, *, document_id: str, operation: str) -> None:
        """插入一条 PENDING 任务，不在仓储内提交事务。"""

        self._session.add(
            DocumentTaskTable(
                id=str(uuid4()),
                document_id=document_id,
                operation=operation,
                status=DocumentTaskStatus.PENDING.value,
                attempts=0,
            )
        )

    async def get(self, entry_id: str) -> DocumentTask | None:
        """按 ID 查任务。"""

        row = await self._session.get(DocumentTaskTable, entry_id)
        return None if row is None else _entry_from_row(row)

    async def list_pending(self, *, limit: int) -> list[DocumentTask]:
        """读取已到重试时间的 PENDING 任务，按创建时间升序。

        FOR UPDATE SKIP LOCKED：多个 publisher 副本并发时各取各的，
        不会把同一行重复投递（与 eval 两条出箱链路口径一致）。
        调用方必须在同一事务里完成 mark_queued + commit，锁才覆盖投递窗口。
        """

        statement = (
            select(DocumentTaskTable)
            .where(
                DocumentTaskTable.status == DocumentTaskStatus.PENDING.value,
                or_(
                    DocumentTaskTable.next_retry_at.is_(None),
                    DocumentTaskTable.next_retry_at <= datetime.now(UTC),
                ),
            )
            .order_by(DocumentTaskTable.created_at, DocumentTaskTable.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = (await self._session.scalars(statement)).all()
        return [_entry_from_row(row) for row in rows]

    async def mark_queued(self, entry_id: str) -> None:
        """PENDING -> QUEUE 记录投递时间。"""

        await self._session.execute(
            update(DocumentTaskTable)
            .where(DocumentTaskTable.id == entry_id)
            .values(
                status=DocumentTaskStatus.QUEUE.value,
                queued_at=datetime.now(UTC),
                last_error=None,
            )
        )

    async def mark_success(self, entry_id: str) -> None:
        """QUEUE -> SUCCESS。"""

        await self._session.execute(
            update(DocumentTaskTable)
            .where(DocumentTaskTable.id == entry_id)
            .values(status=DocumentTaskStatus.SUCCESS.value)
        )

    async def record_failure(self, entry_id: str, *, error: str) -> None:
        """记录一次失败：attempts+1、状态回 PENDING，并按指数退避设置
        下次重试时间（超限终态由调用方随后用 mark_failed 覆盖）。"""

        row = await self._session.get(DocumentTaskTable, entry_id)
        if row is None:
            return
        row.attempts += 1
        row.status = DocumentTaskStatus.PENDING.value
        row.last_error = error[:2000]
        delay = self._retry_backoff_seconds * (2 ** (row.attempts - 1))
        row.next_retry_at = datetime.now(UTC) + timedelta(seconds=delay)

    async def mark_failed(self, entry_id: str) -> None:
        """标记为终态 FAILED。"""

        await self._session.execute(
            update(DocumentTaskTable)
            .where(DocumentTaskTable.id == entry_id)
            .values(status=DocumentTaskStatus.FAILED.value)
        )


def _entry_from_row(row: DocumentTaskTable) -> DocumentTask:
    """ORM 行 -> 领域对象。"""

    return DocumentTask(
        id=row.id,
        document_id=row.document_id,
        operation=row.operation,
        status=DocumentTaskStatus(row.status),
        attempts=row.attempts,
        last_error=row.last_error,
        created_at=row.created_at,
        queued_at=row.queued_at,
    )


__all__ = ["SqlAlchemyDocumentTaskRepository"]
