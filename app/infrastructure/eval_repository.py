"""评测仓储（testsets + items）的 SQLAlchemy 实现。

纯粹的数据访问：收外部传入的 session，**不做 commit**——
事务边界由调用方（service / worker）控制，与 DocumentRepository 的模式一致。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.eval import (
    ChunkRef,
    EvalItemStatus,
    EvalRun,
    EvalRunItem,
    EvalRunStatus,
    EvalTestSet,
    EvalTestSetItem,
    TestSetStatus,
)
from app.infrastructure.tables import (
    EvalRunItemTable,
    EvalRunTable,
    EvalTestSetItemTable,
    EvalTestSetTable,
    utc_now,
)
from app.ports.eval_repository import EvalRepository


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
    return EvalTestSetItem(
        id=row.id,
        answer_document_id=row.answer_document_id,
        answer_chunk_index=row.answer_chunk_index,
        status=EvalItemStatus(row.status),
        query=row.query,
        error_message=row.error_message,
    )


def _run_dto(row: EvalRunTable, *, done: int, total: int) -> EvalRun:
    return EvalRun(
        id=row.id,
        testset_id=row.testset_id,
        status=EvalRunStatus(row.status),
        config=row.config_json,
        metrics=row.metrics_json,
        error_message=row.error_message,
        created_at=row.created_at,
        finished_at=row.finished_at,
        progress_done=done,
        progress_total=total,
    )


def _run_item_dto(
    row: EvalRunItemTable, question: EvalTestSetItemTable
) -> EvalRunItem:
    """逐题结果：题面与坐标从题目行联查带出，结果表里没有副本。"""

    return EvalRunItem(
        testset_item_id=row.testset_item_id,
        query=question.query,
        answer_document_id=question.answer_document_id,
        answer_chunk_index=question.answer_chunk_index,
        hit_rank=row.hit_rank,
        recall=row.recall,
        latency_ms=row.latency_ms,
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
                status=TestSetStatus.GENERATING.value,
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
            ).all()
        )
        if not counts or counts.get(EvalItemStatus.PENDING.value, 0):
            return

        ready = counts.get(EvalItemStatus.READY.value, 0)
        failed = counts.get(EvalItemStatus.FAILED.value, 0)
        # 条件写而不是读-改-写：并发到此处的多个 worker 里，后到的那个
        # 匹配不到行，天然是空操作，所以不需要 FOR UPDATE。
        await self._session.execute(
            update(EvalTestSetTable)
            .where(
                EvalTestSetTable.id == testset_id,
                EvalTestSetTable.status == TestSetStatus.GENERATING.value,
            )
            .values(
                status=(TestSetStatus.READY if ready else TestSetStatus.FAILED).value,
                error_message=f"{failed} 项生成失败" if failed else None,
            )
        )

    async def reopen_testset(self, testset_id: str) -> None:
        await self._session.execute(
            update(EvalTestSetTable)
            .where(EvalTestSetTable.id == testset_id)
            .values(
                status=TestSetStatus.GENERATING.value,
                error_message=None,
            )
        )

    # ---- items ----

    async def add_testset_items(
        self, testset_id: str, refs: list[ChunkRef]
    ) -> None:
        for ref in refs:
            self._session.add(
                EvalTestSetItemTable(
                    id=str(uuid.uuid4()),
                    testset_id=testset_id,
                    status=EvalItemStatus.PENDING.value,
                    answer_document_id=ref.document_id,
                    answer_chunk_index=ref.chunk_index,
                )
            )

    async def list_testset_items(self, testset_id: str) -> list[EvalTestSetItem]:
        rows = (
            await self._session.scalars(
                select(EvalTestSetItemTable)
                .where(EvalTestSetItemTable.testset_id == testset_id)
                .order_by(EvalTestSetItemTable.created_at.asc())
            )
        ).all()
        return [_item_dto(row) for row in rows]

    async def get_item(self, item_id: str) -> EvalTestSetItem | None:
        row = await self._session.get(EvalTestSetItemTable, item_id)
        return _item_dto(row) if row else None

    async def set_item_result(self, item_id: str, *, query: str) -> None:
        row = await _get_item_or_raise(self._session, item_id)
        row.query = query
        row.status = EvalItemStatus.READY.value
        row.error_message = None

    async def set_item_failed(self, item_id: str, *, error: str) -> None:
        row = await _get_item_or_raise(self._session, item_id)
        row.status = EvalItemStatus.FAILED.value
        row.error_message = error

    # ---- runs ----

    async def create_run(
        self, *, run_id: str, testset_id: str, config: dict[str, Any]
    ) -> None:
        self._session.add(
            EvalRunTable(
                id=run_id,
                testset_id=testset_id,
                status=EvalRunStatus.RUNNING.value,
                config_json=config,
            )
        )

    async def record_run_item(self, run_id: str, result: EvalRunItem) -> None:
        self._session.add(
            EvalRunItemTable(
                id=str(uuid.uuid4()),
                run_id=run_id,
                testset_item_id=result.testset_item_id,
                hit_rank=result.hit_rank,
                recall=result.recall,
                latency_ms=result.latency_ms,
            )
        )

    async def finish_run(
        self,
        run_id: str,
        *,
        status: EvalRunStatus,
        metrics: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> None:
        # 条件写：已经不在 running 的 run（被启动扫标过 failed、或重复收尾）匹配不到行，
        # 于是 finished_at 只会有第一次那个值。
        await self._session.execute(
            update(EvalRunTable)
            .where(
                EvalRunTable.id == run_id,
                EvalRunTable.status == EvalRunStatus.RUNNING.value,
            )
            .values(
                status=status.value,
                metrics_json=metrics,
                error_message=error_message,
                finished_at=utc_now(),
            )
        )

    async def get_run(self, run_id: str) -> EvalRun | None:
        row = await self._session.get(EvalRunTable, run_id)
        if row is None:
            return None
        done = await self._scored_counts(run_ids=[run_id])
        total = await self._ready_question_count(row.testset_id)
        return _run_dto(row, done=done.get(run_id, 0), total=total)

    async def list_runs(self, testset_id: str) -> list[EvalRun]:
        rows = (
            await self._session.scalars(
                select(EvalRunTable)
                .where(EvalRunTable.testset_id == testset_id)
                .order_by(EvalRunTable.created_at.desc())
            )
        ).all()
        # 同一测试集的 run 共用一个 total（当前 ready 题数），done 各数各的
        done = await self._scored_counts(run_ids=[row.id for row in rows])
        total = await self._ready_question_count(testset_id)
        return [
            _run_dto(row, done=done.get(row.id, 0), total=total) for row in rows
        ]

    async def list_run_items(self, run_id: str) -> list[EvalRunItem]:
        rows = (
            await self._session.execute(
                select(EvalRunItemTable, EvalTestSetItemTable)
                .join(
                    EvalTestSetItemTable,
                    EvalTestSetItemTable.id == EvalRunItemTable.testset_item_id,
                )
                .where(EvalRunItemTable.run_id == run_id)
                .order_by(EvalRunItemTable.testset_item_id.asc())
            )
        ).all()
        return [_run_item_dto(result, question) for result, question in rows]

    async def list_unscored_questions(self, run_id: str) -> list[EvalTestSetItem]:
        testset_id = await self._session.scalar(
            select(EvalRunTable.testset_id).where(EvalRunTable.id == run_id)
        )
        if testset_id is None:
            return []
        scored = select(EvalRunItemTable.testset_item_id).where(
            EvalRunItemTable.run_id == run_id
        )
        rows = (
            await self._session.scalars(
                select(EvalTestSetItemTable)
                .where(
                    EvalTestSetItemTable.testset_id == testset_id,
                    # ready 隐含 query 非空：set_item_result 是一起写的
                    EvalTestSetItemTable.status == EvalItemStatus.READY.value,
                    EvalTestSetItemTable.id.not_in(scored),
                )
                .order_by(EvalTestSetItemTable.created_at.asc())
            )
        ).all()
        return [_item_dto(row) for row in rows]

    async def fail_stale_runs(self, *, error: str) -> int:
        rows = (
            await self._session.execute(
                update(EvalRunTable)
                .where(EvalRunTable.status == EvalRunStatus.RUNNING.value)
                .values(
                    status=EvalRunStatus.FAILED.value,
                    error_message=error,
                    finished_at=utc_now(),
                )
                .returning(EvalRunTable.id)
            )
        ).all()
        return len(rows)

    # ---- 派生进度 ----

    async def _progress(self, testset_id: str | None = None) -> dict[str, tuple[int, int]]:
        """各测试集的 (done, total)。

        done 计入 ready 和 failed：失败条目也是「生成完了」，
        否则进度条永远差几格，和 finalize_testset 的完成条件也不一致。
        """
        stmt = (
            select(
                EvalTestSetItemTable.testset_id,
                func.count().filter(
                    EvalTestSetItemTable.status != EvalItemStatus.PENDING.value
                ),
                func.count(),
            )
            .group_by(EvalTestSetItemTable.testset_id)
        )
        if testset_id is not None:
            stmt = stmt.where(EvalTestSetItemTable.testset_id == testset_id)
        rows = (await self._session.execute(stmt)).all()
        return {str(row[0]): (int(row[1]), int(row[2])) for row in rows}

    async def _scored_counts(self, *, run_ids: list[str]) -> dict[str, int]:
        """各 run 已写出几题结果：一次分组查询，列表页不给每行查一次。"""

        if not run_ids:
            return {}
        rows = (
            await self._session.execute(
                select(EvalRunItemTable.run_id, func.count())
                .where(EvalRunItemTable.run_id.in_(run_ids))
                .group_by(EvalRunItemTable.run_id)
            )
        ).all()
        return {str(row[0]): int(row[1]) for row in rows}

    async def _ready_question_count(self, testset_id: str) -> int:
        """run 的分母：测试集里当前 ready 的题数。

        是「当前」而不是「开跑那一刻」—— 没有题级快照，所以 run 跑完之后再往
        集里加题，历史 run 的 total 会跟着涨。真要看某次跑了几题，
        metrics 里的 queries 才是那次的事实。
        """

        count = await self._session.scalar(
            select(func.count())
            .select_from(EvalTestSetItemTable)
            .where(
                EvalTestSetItemTable.testset_id == testset_id,
                EvalTestSetItemTable.status == EvalItemStatus.READY.value,
            )
        )
        return int(count or 0)


__all__ = ["SqlAlchemyEvalRepository"]
