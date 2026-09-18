"""评测仓储（testsets + items）的 SQLAlchemy 实现。

纯粹的数据访问：收外部传入的 session，**不做 commit**——
事务边界由调用方（service / worker）控制，与 DocumentRepository 的模式一致。
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.eval import (
    ChunkRef,
    EvalItemStatus,
    EvalTestSet,
    EvalTestSetItem,
    TestSetStatus,
)
from app.infrastructure.postgres.tables import (
    EvalTestSetItemEvidenceTable,
    EvalTestSetItemTable,
    EvalTestSetTable,
)
from app.ports.persistence.eval_repository import EvalRepository


def _testset_dto(row: EvalTestSetTable, *, done: int, total: int) -> EvalTestSet:
    return EvalTestSet(
        id=row.id,
        name=row.name,
        status=TestSetStatus(row.status),
        progress_done=done,
        progress_total=total,
        error_message=row.error_message,
        created_at=row.created_at,
    )


def _item_dto(row: EvalTestSetItemTable) -> EvalTestSetItem:
    """Coordinates come from the loaded relationship (selectinload)."""

    return EvalTestSetItem(
        id=row.id,
        status=EvalItemStatus(row.status),
        query=row.query,
        error_message=row.error_message,
        evidence=[
            ChunkRef(document_id=e.document_id, chunk_index=e.chunk_index)
            for e in row.evidence
        ],
    )


async def _get_item_or_raise(session: AsyncSession, item_id: str) -> EvalTestSetItemTable:
    row = await session.get(EvalTestSetItemTable, item_id)
    if row is None:
        raise KeyError(item_id)
    return row


class SqlAlchemyEvalRepository(EvalRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---- testsets ----

    async def create_testset(self, *, testset_id: str, name: str) -> None:
        self._session.add(
            EvalTestSetTable(
                id=testset_id,
                name=name,
                status=TestSetStatus.GENERATING,
            )
        )

    async def get_testset(self, testset_id: str) -> EvalTestSet | None:
        row = await self._session.get(EvalTestSetTable, testset_id)
        if row is None:
            return None
        progress = await self._progress(testset_id=testset_id)
        done, total = progress.get(testset_id, (0, 0))
        return _testset_dto(row, done=done, total=total)

    async def list_testsets(self) -> list[EvalTestSet]:
        rows = (
            await self._session.scalars(
                select(EvalTestSetTable).order_by(EvalTestSetTable.created_at.desc())
            )
        ).all()
        progress = await self._progress()
        result: list[EvalTestSet] = []
        for row in rows:
            done, total = progress.get(row.id, (0, 0))
            result.append(_testset_dto(row, done=done, total=total))
        return result

    async def delete_testset(self, testset_id: str) -> None:
        await self._session.execute(
            delete(EvalTestSetTable).where(EvalTestSetTable.id == testset_id)
        )

    async def finalize_testset(self, testset_id: str) -> None:
        # 按 status 分组数一次，完成条件和终态统计都从这份计数出来。
        # 依赖 autoflush：调用方在同一 session 里改过 item 状态，
        # 这条 select 会先把改动 flush 到 DB，计数才包含本次写入。
        counts = dict(
            (
                await self._session.execute(
                    select(EvalTestSetItemTable.status, func.count())
                    .where(EvalTestSetItemTable.testset_id == testset_id)
                    .group_by(EvalTestSetItemTable.status)
                )
            ).tuples().all()
        )# testset 的 PENDING READY FAILED 的人数
        if not counts or counts.get(EvalItemStatus.PENDING, 0):
            # 还有PENDING的直接返回
            return
        # 全部完成 要吗failed 要吗 ready
        ready = counts.get(EvalItemStatus.READY, 0)
        failed = counts.get(EvalItemStatus.FAILED, 0)
        # 条件写而不是读-改-写：并发到此处的多个 worker 里，后到的那个
        # 匹配不到行，天然是空操作，所以不需要 FOR UPDATE。
        await self._session.execute(
            update(EvalTestSetTable)
            .where(
                EvalTestSetTable.id == testset_id,
                EvalTestSetTable.status == TestSetStatus.GENERATING,
            )
            .values(
                status=(TestSetStatus.READY if ready else TestSetStatus.FAILED).value,
                error_message=f"{failed} 项生成失败" if failed else None,
            )
        )

    async def reopen_testset(self, testset_id: str) -> None:
        """直接设置status即可 publisher会自己发送出去"""
        await self._session.execute(
            update(EvalTestSetTable)
            .where(EvalTestSetTable.id == testset_id)
            .values(
                status=TestSetStatus.GENERATING,
                error_message=None,
            )
        )

    # ---- items ----

    async def add_testset_items(
        self, testset_id: str, groups: list[list[ChunkRef]]
    ) -> list[str]:
        """testset_id 和 [[chunkref]] 创建testset item"""
        ids: list[str] = []
        for group in groups:
            item_id = str(uuid.uuid4())
            ids.append(item_id)
            self._session.add(
                EvalTestSetItemTable(
                    id=item_id,
                    testset_id=testset_id,
                    status=EvalItemStatus.PENDING,
                )
            )
            # unique(item_id, ordinal)，顺序即入参顺序。
            for ordinal, ref in enumerate(dict.fromkeys(group)):
                self._session.add(
                    EvalTestSetItemEvidenceTable(
                        item_id=item_id,
                        document_id=ref.document_id,
                        chunk_index=ref.chunk_index,
                        ordinal=ordinal,
                    )
                )
        return ids # 插入成功的id

    async def delete_items_referencing_document(self, document_id: str) -> int:
        """联级删除 document id 删掉所有的引用document中的chunk作为evidence的testset item"""

        evidence_item_ids = select(EvalTestSetItemEvidenceTable.item_id).where(
            EvalTestSetItemEvidenceTable.document_id == document_id
        )
        result = await self._session.execute(
            delete(EvalTestSetItemTable).where(
                EvalTestSetItemTable.id.in_(evidence_item_ids)
            )
        )
        return int(result.rowcount or 0)

    async def list_testset_items(self, testset_id: str) -> list[EvalTestSetItem]:
        rows = (
            await self._session.scalars(
                select(EvalTestSetItemTable)
                .options(selectinload(EvalTestSetItemTable.evidence))
                .where(EvalTestSetItemTable.testset_id == testset_id)
                .order_by(EvalTestSetItemTable.created_at.asc())
            )
        ).all()
        return [_item_dto(row) for row in rows]

    async def get_item(self, item_id: str) -> EvalTestSetItem | None:
        row = await self._session.scalar(
            select(EvalTestSetItemTable)
            .options(selectinload(EvalTestSetItemTable.evidence))
            .where(EvalTestSetItemTable.id == item_id)
        )
        return None if row is None else _item_dto(row)

    async def set_item_result(self, item_id: str, *, query: str) -> None:
        row = await _get_item_or_raise(self._session, item_id)
        row.query = query
        row.status = EvalItemStatus.READY
        row.error_message = None

    async def set_item_failed(self, item_id: str, *, error: str) -> None:
        row = await _get_item_or_raise(self._session, item_id)
        row.status = EvalItemStatus.FAILED
        row.error_message = error

    async def set_item_pending_retry(self, item_id: str) -> None:
        row = await _get_item_or_raise(self._session, item_id)
        row.status = EvalItemStatus.PENDING
        row.query = None
        row.error_message = None

    # ---- 派生进度 ----

    async def _progress(self, testset_id: str | None = None) -> dict[str, tuple[int, int]]:
        """各测试集的 (done, total)：非 PENDING 即视为完成（READY/FAILED）。

        testset_id 为 None 时返回全部集合的数据，否则只算指定集合。
        """
        stmt = (
            select(
                EvalTestSetItemTable.testset_id,
                func.count().filter(
                    EvalTestSetItemTable.status != EvalItemStatus.PENDING
                ),
                func.count(),
            )
            .group_by(EvalTestSetItemTable.testset_id)
        )
        if testset_id is not None:
            stmt = stmt.where(EvalTestSetItemTable.testset_id == testset_id)
        rows = (await self._session.execute(stmt)).all()
        return {str(row[0]): (int(row[1]), int(row[2])) for row in rows} # testset_id done total

__all__ = ["SqlAlchemyEvalRepository"]
