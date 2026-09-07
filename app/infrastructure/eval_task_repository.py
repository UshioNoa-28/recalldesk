"""出题任务发件箱（eval_tasks）的 SQLAlchemy 实现。

纯粹的数据访问：收外部传入的 session，不做 commit——
publisher / worker 各自管理短事务，与 outbox_repository 的模式一致。

只碰 eval_tasks 表：题目快照与测试集状态在 SqlAlchemyEvalRepository。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.eval import EvalTask, EvalTaskStatus
from app.infrastructure.tables import EvalTaskTable
from app.ports.eval_task_repository import EvalTaskRepository
from settings import settings


def _task_dto(row: EvalTaskTable) -> EvalTask:
    return EvalTask(
        id=row.id,
        testset_id=row.testset_id,
        item_id=row.item_id,
        status=EvalTaskStatus(row.status),
        attempts=row.attempts,
        last_error=row.last_error,
        created_at=row.created_at,
        queued_at=row.queued_at,
    )


async def _get_task_or_raise(session: AsyncSession, task_id: str) -> EvalTaskTable:
    row = await session.get(EvalTaskTable, task_id)
    if row is None:
        raise KeyError(task_id)
    return row


class SqlAlchemyEvalTaskRepository(EvalTaskRepository):
    def __init__(self, session) -> None:
        self._session = session

    async def add(self, *, testset_id: str, item_id: str) -> None:
        self._session.add(
            EvalTaskTable(
                id=str(uuid.uuid4()),
                testset_id=testset_id,
                item_id=item_id,
                status=EvalTaskStatus.PENDING.value,
            )
        )

    async def get(self, task_id: str) -> EvalTask | None:
        row = await self._session.get(EvalTaskTable, task_id)
        return _task_dto(row) if row else None

    async def list_pending(self, *, limit: int) -> list[EvalTask]:
        # FOR UPDATE SKIP LOCKED：多 publisher 并发领取互不重复，
        # 锁持有到本事务 commit（Redis 投递后立即 mark_queued + commit）。
        # 只领取已到重试时间的任务（失败任务按指数退避等待）。
        rows = (
            await self._session.scalars(
                select(EvalTaskTable)
                .where(
                    EvalTaskTable.status == EvalTaskStatus.PENDING.value,
                    or_(
                        EvalTaskTable.next_retry_at.is_(None),
                        EvalTaskTable.next_retry_at <= datetime.now(UTC),
                    ),
                )
                .order_by(EvalTaskTable.created_at.asc(), EvalTaskTable.id.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
        return [_task_dto(row) for row in rows]

    async def mark_queued(self, task_id: str) -> None:
        row = await _get_task_or_raise(self._session, task_id)
        row.status = EvalTaskStatus.QUEUE.value
        row.queued_at = datetime.now(UTC)

    async def mark_success(self, task_id: str) -> None:
        row = await _get_task_or_raise(self._session, task_id)
        row.status = EvalTaskStatus.SUCCESS.value

    async def record_failure(self, task_id: str, *, error: str) -> None:
        """记录一次失败：attempts+1、状态回 PENDING，并按指数退避设置
        下次重试时间（超限终态由调用方随后用 mark_failed 覆盖）。"""

        row = await _get_task_or_raise(self._session, task_id)
        row.attempts += 1
        row.status = EvalTaskStatus.PENDING.value
        row.last_error = error
        delay = settings.eval_task_retry_backoff_base_seconds * (2 ** (row.attempts - 1))
        row.next_retry_at = datetime.now(UTC) + timedelta(seconds=delay)

    async def mark_failed(self, task_id: str) -> None:
        row = await _get_task_or_raise(self._session, task_id)
        row.status = EvalTaskStatus.FAILED.value


__all__ = ["SqlAlchemyEvalTaskRepository"]
