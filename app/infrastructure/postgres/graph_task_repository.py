"""graph_tasks 表（Transactional Outbox）的 SQLAlchemy 实现。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.graph import GraphTask, GraphTaskStatus
from app.infrastructure.postgres.tables import GraphTaskTable
from app.ports.persistence.graph_task_repository import GraphTaskRepository


class SqlAlchemyGraphTaskRepository(GraphTaskRepository):
    """在调用方提供的 Session 中读写 graph_tasks 表。"""

    def __init__(self, session: AsyncSession, *, retry_backoff_seconds: float = 30.0) -> None:
        self._session = session
        self._retry_backoff_seconds = retry_backoff_seconds

    async def add(self, *, document_id: str) -> None:
        """插入一条 PENDING 任务，不在仓储内提交事务。"""

        self._session.add(
            GraphTaskTable(
                id=str(uuid4()),
                document_id=document_id,
                operation="extract",
                status=GraphTaskStatus.PENDING,
                attempts=0,
            )
        )

    async def get(self, entry_id: str) -> GraphTask | None:
        row = await self._session.get(GraphTaskTable, entry_id)
        return None if row is None else _entry_from_row(row)

    async def list_pending(self, *, limit: int) -> list[GraphTask]:
        """读取已到重试时间的 PENDING 任务，按创建时间升序。

        FOR UPDATE SKIP LOCKED：多 publisher 副本并发领取互不重复；
        调用方必须在同一事务里完成 mark_queued + commit。
        """

        statement = (
            select(GraphTaskTable)
            .where(
                GraphTaskTable.status == GraphTaskStatus.PENDING,
                or_(
                    GraphTaskTable.next_retry_at.is_(None),
                    GraphTaskTable.next_retry_at <= datetime.now(UTC),
                ),
            )
            .order_by(GraphTaskTable.created_at, GraphTaskTable.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = (await self._session.scalars(statement)).all()
        return [_entry_from_row(row) for row in rows]

    async def mark_queued(self, entry_id: str) -> None:
        await self._session.execute(
            update(GraphTaskTable)
            .where(GraphTaskTable.id == entry_id)
            .values(
                status=GraphTaskStatus.QUEUE,
                queued_at=datetime.now(UTC),
                last_error=None,
            )
        )

    async def mark_success(self, entry_id: str) -> None:
        await self._session.execute(
            update(GraphTaskTable)
            .where(GraphTaskTable.id == entry_id)
            .values(status=GraphTaskStatus.SUCCESS)
        )

    async def record_failure(self, entry_id: str, *, error: str) -> None:
        """attempts+1、回 PENDING、指数退避（超限终态由调用方 mark_failed 覆盖）。"""

        row = await self._session.get(GraphTaskTable, entry_id)
        if row is None:
            return
        row.attempts += 1
        row.status = GraphTaskStatus.PENDING
        row.last_error = error[:2000]
        delay = self._retry_backoff_seconds * (2 ** (row.attempts - 1))
        row.next_retry_at = datetime.now(UTC) + timedelta(seconds=delay)

    async def mark_failed(self, entry_id: str) -> None:
        await self._session.execute(
            update(GraphTaskTable)
            .where(GraphTaskTable.id == entry_id)
            .values(status=GraphTaskStatus.FAILED)
        )

    async def latest_for_document_ids(
        self, document_ids: list[str]
    ) -> dict[str, tuple[str, str | None]]:
        if not document_ids:
            return {}
        rows = (
            await self._session.execute(
                select(
                    GraphTaskTable.document_id,
                    GraphTaskTable.status,
                    GraphTaskTable.last_error,
                )
                .where(GraphTaskTable.document_id.in_(document_ids))
                .distinct(GraphTaskTable.document_id)
                .order_by(GraphTaskTable.document_id, GraphTaskTable.created_at.desc())
            )
        ).all()
        return {str(r[0]): (str(r[1]), r[2]) for r in rows}

    async def queue_extraction(self, document_id: str) -> str:
        """在途不排队套排队；failed/success 复位原行；没有历史才新建。"""

        latest = (
            await self._session.scalars(
                select(GraphTaskTable)
                .where(GraphTaskTable.document_id == document_id)
                .order_by(GraphTaskTable.created_at.desc())
                .limit(1)
            )
        ).first()
        if latest is None:
            await self.add(document_id=document_id)
            return "created"
        if latest.status in (GraphTaskStatus.PENDING, GraphTaskStatus.QUEUE):
            raise ValueError("该文档的图谱抽取正在进行中，等它落定再重跑")
        latest.status = GraphTaskStatus.PENDING
        latest.attempts = 0
        latest.last_error = None
        latest.next_retry_at = None
        return "requeued"


def _entry_from_row(row: GraphTaskTable) -> GraphTask:
    return GraphTask(
        id=row.id,
        document_id=row.document_id,
        status=GraphTaskStatus(row.status),
        attempts=row.attempts,
        last_error=row.last_error,
        created_at=row.created_at,
        queued_at=row.queued_at,
    )


__all__ = ["SqlAlchemyGraphTaskRepository"]
