"""评测运行聚合的表：runs / 逐题结果 / 逐题评测任务发件箱。"""

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
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.postgres.tables.base import Base, utc_now


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

    只存不可再生的事实：每块证据的名次、期望文档是否进 top-k、证据块数快照、
    这条查询的耗时。joint_hit / map 都是这些列的纯函数，都在 DTO 上算 ——
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
    latency_ms: Mapped[float] = mapped_column(Double, nullable=False, default=0.0)
    # 证据覆盖（打分时快照）：coverage = matched/total，图频道是否把缺的块捞回来了
    evidence_total: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    evidence_matched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 每块被捞回证据的名次（升序）：map@k 的原料，0015 新增；老行为 NULL，聚合按 0 计
    evidence_ranks_json: Mapped[list[int] | None] = mapped_column(JSONB, nullable=True)


class EvalRunTaskTable(Base):
    """eval_run_tasks 表：逐题评测任务发件箱（一次 run 开跑时 fan-out）。

    与 eval_tasks 同款状态机（EvalTaskStatus），但归属不同：一条任务属于
    一个 run 而不是测试集——run 是「此刻这批题」的快照，题目后来被删时
    CASCADE 连任务一起带走，留下的结果行走联查诚实消失的老路。
    """

    __tablename__ = "eval_run_tasks"
    __table_args__ = (
        # 一题在一次 run 里只有一条任务：重投是复位这一行，不是补发新行
        UniqueConstraint("run_id", "item_id", name="uq_eval_run_tasks_run_item"),
        # publisher 扫 PENDING（含退避时间过滤）
        Index("ix_eval_run_tasks_status_next_retry", "status", "next_retry_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("eval_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("eval_testset_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = [
    "EvalRunItemTable",
    "EvalRunTable",
    "EvalRunTaskTable",
]
