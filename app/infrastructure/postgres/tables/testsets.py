"""测试集聚合的表：testsets / items / 证据集合 / 出题任务发件箱。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.postgres.tables.base import Base, utc_now


class EvalTestSetTable(Base):
    """eval_testsets 测评集 由LLM根据提供的chunk出题组成"""

    __tablename__ = "eval_testsets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="generating")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    # unit-of-work 按 relationship 而不是表外键给 INSERT 排序：少了这两条，
    # 父子同事务写入会先插子表直接撞 fkey
    items: Mapped[list[EvalTestSetItemTable]] = relationship(lazy="raise")
    # lazy="raise" 懒加载直接报错 为了防止n+1问题 强制要求 selectinload 或者 joinedload


class EvalTestSetItemTable(Base):
    """一个具体的testset item """

    __tablename__ = "eval_testset_items"
    __table_args__ = (
        # 进度聚合 / finalize 都按 (testset_id, status) 计数
        Index("ix_eval_items_testset_status", "testset_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    testset_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("eval_testsets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ) # 随主表联级删除
    query: Mapped[str | None] = mapped_column(Text, nullable=True) # llm 根据 chunk出的 query
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    tasks: Mapped[list[EvalTaskTable]] = relationship(lazy="raise")
    evidence: Mapped[list[EvalTestSetItemEvidenceTable]] = relationship(
        lazy="raise",
        # read side uses selectinload; assembly order is pinned here
        order_by="EvalTestSetItemEvidenceTable.ordinal",
    ) # 出题依赖的chunk 答案


class EvalTestSetItemEvidenceTable(Base):
    """eval_testset_item_evidence 多对多 testset item 和 chunk"""

    __tablename__ = "eval_testset_item_evidence"
    __table_args__ = (
        UniqueConstraint("item_id", "ordinal", name="uq_eval_evidence_item_ordinal"),
    )

    item_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("eval_testset_items.id", ondelete="CASCADE"),
        primary_key=True,
    )
    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("documents.id", ondelete="RESTRICT"),
        primary_key=True,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 出题时多个chunk拼装的顺序 类似于seq号 和 item_id 组成unique constrain
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class EvalTaskTable(Base):
    """eval_tasks 表：出题任务发件箱（业务事务内写入，worker 异步投递）。"""

    __tablename__ = "eval_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    testset_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("eval_testsets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("eval_testset_items.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = [
    "EvalTaskTable",
    "EvalTestSetItemEvidenceTable",
    "EvalTestSetItemTable",
    "EvalTestSetTable",
]
