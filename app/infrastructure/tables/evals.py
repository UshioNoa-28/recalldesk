"""评测侧表：测试集（含题目与出题任务）与运行（含逐题结果）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.tables.base import Base, utc_now


class EvalTestSetTable(Base):
    """eval_testsets 表：评测集（LLM 反向出题生成）。

    没有进度列：出题进度由 eval_testset_items 的 status 聚合算出，
    存计数器就得在并发下小心维护，而条目状态本身就是那份事实。
    """

    __tablename__ = "eval_testsets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="generating")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    # unit-of-work 按 relationship 而不是表外键给 INSERT 排序：少了这两条，
    # 父子同事务写入会先插子表直接撞 fkey。lazy="raise" 是因为没有代码遍历
    # 它们，异步下隐式懒加载会 MissingGreenlet。
    items: Mapped[list[EvalTestSetItemTable]] = relationship(lazy="raise")


class EvalTestSetItemTable(Base):
    """eval_testset_items 表：题目 = 出题素材的坐标 + LLM 生成的问题。

    不存原文副本：分块文本的唯一权威在 Qdrant，坐标可算出点 id，出题时回查。
    所以 answer_document_id 必须是真外键 —— 文档被删则它的点一起消失，题目
    再没有可命中的 ground truth，留着只会在 run 里稳定判错，于是级联删掉。
    """

    __tablename__ = "eval_testset_items"
    __table_args__ = (
        # 进度聚合 / finalize 都按 (testset_id, status) 计数
        Index("ix_eval_items_testset_status", "testset_id", "status"),
        # 一个 chunk 在一个测试集里只出一道题（想出一个 chunk 多版本要先解掉）
        UniqueConstraint(
            "testset_id",
            "answer_document_id",
            "answer_chunk_index",
            name="uq_eval_testset_items_testset_chunk",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    testset_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("eval_testsets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    answer_chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    tasks: Mapped[list[EvalTaskTable]] = relationship(lazy="raise")


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


class EvalRunTable(Base):
    """eval_runs 表：一次评测运行（测试集 + 配置快照 + 聚合指标）。

    没有进度列：跑完几题看 eval_run_items 有几行就知道，存计数器就得在每题写入
    时小心维护，而结果行本身就是那份事实。config_json 是**快照**而不是状态：
    top_k 决定 recall@k 的 k、query_rewrite 决定检索走的哪条路，两次 run 要能
    比较，就得知道当时各自用的是什么。
    """

    __tablename__ = "eval_runs"
    __table_args__ = (
        # 一个测试集同时最多一个 running：EvalRunService._require_idle 的
        # 「先查再插」有并发窗口，这里用部分唯一索引兜底（只约束 running 行）
        Index(
            "uq_eval_runs_running_per_testset",
            "testset_id",
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    testset_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("eval_testsets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    config_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    metrics_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EvalRunItemTable(Base):
    """eval_run_items 表：逐题结果。

    只存不可再生的三列：期望切片的名次、期望文档是否进 top-k、这条查询的耗时。
    mrr 是 hit_rank 的倒数、low_recall 是 recall 是否为 0，都在 DTO 上算 ——
    落列就得在改口径时回来同步历史行。
    不存题面与坐标：联查 eval_testset_items 就有，抄一份会在题目被改删之后
    开始对不上真正被问的那个东西。
    """

    __tablename__ = "eval_run_items"
    __table_args__ = (
        # 一题在一次 run 里只有一条结果，执行器靠它保证「重跑不重复写」
        UniqueConstraint("run_id", "testset_item_id", name="uq_eval_run_items_run_item"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("eval_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    testset_item_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("eval_testset_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    hit_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recall: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[float] = mapped_column(Double, nullable=False, default=0.0)


__all__ = [
    "EvalRunItemTable",
    "EvalRunTable",
    "EvalTaskTable",
    "EvalTestSetItemTable",
    "EvalTestSetTable",
]
