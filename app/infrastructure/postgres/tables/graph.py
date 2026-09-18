"""图谱侧表：graph_tasks（文档→图抽取任务发件箱）。

图本体（Entity 节点与带 evidence 的 REL 边）存在 Neo4j，这里没有镜像表：
PG 只管两件事——任务的可靠投递（outbox）与文档行存在性。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.postgres.tables.base import Base, utc_now


class GraphTaskTable(Base):
    """graph_tasks 表：文档索引成功后入队，worker 异步抽取实体关系灌进 Neo4j。"""

    __tablename__ = "graph_tasks"
    __table_args__ = (
        # publisher 扫 PENDING（含退避时间过滤）
        Index("ix_graph_tasks_status_next_retry", "status", "next_retry_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String(16), nullable=False, default="extract")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = ["GraphTaskTable"]
