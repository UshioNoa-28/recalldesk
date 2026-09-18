"""逐题评测任务发件箱（eval_run_tasks）的 SQLAlchemy 实现。

纯粹的数据访问：收外部传入的 session，不做 commit——
publisher / consumer 各自管理短事务，与出题任务（eval_task_repository）同形。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.eval import EvalRunTask, EvalTaskStatus
from app.infrastructure.postgres.tables import EvalRunTaskTable
from app.ports.persistence.eval_run_task_repository import EvalRunTaskRepository


def _task_dto(row: EvalRunTaskTable) -> EvalRunTask:
    return EvalRunTask(
        id=row.id,
        run_id=row.run_id,
        item_id=row.item_id,
        status=EvalTaskStatus(row.status),
        attempts=row.attempts,
        last_error=row.last_error,
        created_at=row.created_at,
        queued_at=row.queued_at,
    )


async def _get_task_or_raise(session: AsyncSession, task_id: str) -> EvalRunTaskTable:
    row = await session.get(EvalRunTaskTable, task_id)
    if row is None:
        raise KeyError(task_id)
    return row


class SqlAlchemyEvalRunTaskRepository(EvalRunTaskRepository):
    def __init__(self, session: AsyncSession, *, retry_backoff_seconds: float = 10.0) -> None:
        self._session = session
        self._retry_backoff_seconds = retry_backoff_seconds

    async def add(self, *, run_id: str, item_id: str) -> None:
        self._session.add(
            EvalRunTaskTable(
                id=str(uuid.uuid4()),
                run_id=run_id,
                item_id=item_id,
                status=EvalTaskStatus.PENDING,
            )
        )

    async def get(self, task_id: str) -> EvalRunTask | None:
        row = await self._session.get(EvalRunTaskTable, task_id)
        return _task_dto(row) if row else None

    async def list_pending(self, *, limit: int) -> list[EvalRunTask]:
        # FOR UPDATE SKIP LOCKED：多 publisher 并发领取互不重复，
        # 锁持有到本事务 commit（Redis 投递后立即 mark_queued + commit）。
        # 只领取已到重试时间的任务（失败任务按指数退避等待）。
        rows = (
            await self._session.scalars(
                select(EvalRunTaskTable)
                .where(
                    EvalRunTaskTable.status == EvalTaskStatus.PENDING,
                    or_(
                        EvalRunTaskTable.next_retry_at.is_(None),
                        EvalRunTaskTable.next_retry_at <= datetime.now(UTC),
                    ),
                )
                .order_by(EvalRunTaskTable.created_at.asc(), EvalRunTaskTable.id.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
        return [_task_dto(row) for row in rows]

    async def mark_queued(self, task_id: str) -> None:
        row = await _get_task_or_raise(self._session, task_id)
        row.status = EvalTaskStatus.QUEUE
        row.queued_at = datetime.now(UTC)

    async def mark_success(self, task_id: str) -> None:
        row = await _get_task_or_raise(self._session, task_id)
        row.status = EvalTaskStatus.SUCCESS

    async def record_failure(self, task_id: str, *, error: str) -> None:
        """记录一次失败：attempts+1、状态回 PENDING，并按指数退避设置
        下次重试时间（超限终态由调用方随后用 mark_failed 覆盖）。"""

        row = await _get_task_or_raise(self._session, task_id)
        row.attempts += 1
        row.status = EvalTaskStatus.PENDING
        row.last_error = error
        delay = self._retry_backoff_seconds * (2 ** (row.attempts - 1))
        row.next_retry_at = datetime.now(UTC) + timedelta(seconds=delay)

    async def mark_failed(self, task_id: str) -> None:
        row = await _get_task_or_raise(self._session, task_id)
        row.status = EvalTaskStatus.FAILED

    async def reset_failed_for_run(self, run_id: str) -> int:
        result = await self._session.execute(
            update(EvalRunTaskTable)
            .where(
                EvalRunTaskTable.run_id == run_id,
                EvalRunTaskTable.status == EvalTaskStatus.FAILED,
            )
            .values(
                status=EvalTaskStatus.PENDING,
                attempts=0,
                last_error=None,
                next_retry_at=None,
            )
        )
        return int(result.rowcount or 0)

    async def count_by_status(self, run_id: str) -> dict[str, int]:
        rows = (
            await self._session.execute(
                select(EvalRunTaskTable.status, func.count())
                .where(EvalRunTaskTable.run_id == run_id)
                .group_by(EvalRunTaskTable.status)
            )
        ).all()
        return {str(row[0]): int(row[1]) for row in rows}


__all__ = ["SqlAlchemyEvalRunTaskRepository"]
