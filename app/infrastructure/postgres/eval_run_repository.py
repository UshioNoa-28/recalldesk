"""评测 run 仓储（runs + 逐题结果）的 SQLAlchemy 实现。

与 testsets/items 侧的 SqlAlchemyEvalRepository 分家：run 的读写只碰
eval_runs / eval_run_items，题面靠 join，不复制。

纯粹的数据访问：收外部传入的 session，**不做 commit**——
事务边界由调用方（service / worker）控制，与 DocumentRepository 的模式一致。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.eval import (
    ChunkRef,
    EvalItemStatus,
    EvalRun,
    EvalRunItem,
    EvalRunStatus,
    EvalTestSetItem,
)
from app.domain.eval_metrics import aggregate
from app.infrastructure.postgres.tables import (
    EvalRunItemTable,
    EvalRunTable,
    EvalTestSetItemTable,
    utc_now,
)
from app.ports.persistence.eval_run_repository import EvalRunRepository


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
    row: EvalRunItemTable,
    question: EvalTestSetItemTable,
) -> EvalRunItem:
    """逐题结果：题面从题目行联查带出，结果表没有副本（坐标走 evidence 由前端自查）。"""

    return EvalRunItem(
        testset_item_id=row.testset_item_id,
        query=question.query,
        hit_rank=row.hit_rank,
        latency_ms=row.latency_ms,
        evidence_total=row.evidence_total,
        evidence_matched=row.evidence_matched,
        evidence_ranks=list(row.evidence_ranks_json) if row.evidence_ranks_json else None,
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


class SqlAlchemyEvalRunRepository(EvalRunRepository):
    """一次 run 的一生：建行、写逐题结果、聚合收尾、重开。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_run(
        self, *, run_id: str, testset_id: str, config: dict[str, Any]
    ) -> None:
        self._session.add(
            EvalRunTable(
                id=run_id,
                testset_id=testset_id,
                status=EvalRunStatus.RUNNING,
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
                latency_ms=result.latency_ms,
                evidence_total=result.evidence_total,
                evidence_matched=result.evidence_matched,
                evidence_ranks_json=result.evidence_ranks,
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
                EvalRunTable.status == EvalRunStatus.RUNNING,
            )
            .values(
                status=status,
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
        # 题面从 items 行联查（0013 后坐标只在 evidence 表，run 结果不再投影主坐标）；
        # items 走 inner join（题被级联删则结果一并消失，见 EvalRepository 端口注释）
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
                    EvalTestSetItemTable.status == EvalItemStatus.READY,
                    EvalTestSetItemTable.id.not_in(scored),
                )
                .options(selectinload(EvalTestSetItemTable.evidence))
                .order_by(EvalTestSetItemTable.created_at.asc())
            )
        ).all()
        return [_item_dto(row) for row in rows]

    async def has_run_result(self, run_id: str, testset_item_id: str) -> bool:
        value = await self._session.scalar(
            select(EvalRunItemTable.id)
            .where(
                EvalRunItemTable.run_id == run_id,
                EvalRunItemTable.testset_item_id == testset_item_id,
            )
            .limit(1)
        )
        return value is not None

    async def finalize_run(self, run_id: str, *, pending_open: int, failed: int) -> None:
        if pending_open:
            return  # 还有在途任务，谁爱数谁数，收尾轮不到这次
        row = await self._session.get(EvalRunTable, run_id)
        if row is None or row.status != EvalRunStatus.RUNNING:
            return  # run 已删除或已终态：重复/并发 finalize 都是空操作
        if failed:
            # 残缺指标不如没有：有题永久失败时不发布 DONE，
            # 免得 recall@k 悄悄用一个小分母冒充完整评测
            await self.finish_run(
                run_id,
                status=EvalRunStatus.FAILED,
                error_message=f"{failed} 道题评测失败",
            )
            return
        k = int(row.config_json.get("top_k", 0) or 0)
        metrics = aggregate(await self.list_run_items(run_id), k=k)
        await self.finish_run(run_id, status=EvalRunStatus.DONE, metrics=metrics)

    async def reopen_run(self, run_id: str) -> None:
        await self._session.execute(
            update(EvalRunTable)
            .where(
                EvalRunTable.id == run_id,
                EvalRunTable.status == EvalRunStatus.FAILED,
            )
            .values(status=EvalRunStatus.RUNNING, error_message=None, finished_at=None)
        )

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
                EvalTestSetItemTable.status == EvalItemStatus.READY,
            )
        )
        return int(count or 0)


__all__ = ["SqlAlchemyEvalRunRepository"]
