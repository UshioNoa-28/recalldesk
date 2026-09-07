"""文档侧表：documents（文档元数据）与 document_tasks（索引任务发件箱）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.documents import Document, DocumentStatus
from app.infrastructure.tables.base import Base, utc_now


class DocumentTable(Base):
    """documents 表：保存原始文件的引用和索引状态。"""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    media_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DocumentTaskTable(Base):
    """document_tasks 表：业务事务内写入、worker 异步投递的任务发件箱。"""

    __tablename__ = "document_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def document_from_row(row: DocumentTable) -> Document:
    """ORM 行 -> 领域实体。"""

    return Document(
        id=row.id,
        name=row.name,
        storage_key=row.storage_key,
        size_bytes=row.size_bytes,
        checksum_sha256=row.checksum_sha256,
        media_type=row.media_type,
        status=DocumentStatus(row.status),
        chunk_count=row.chunk_count,
        error_message=row.error_message,
        created_at=row.created_at,
        indexed_at=row.indexed_at,
    )


__all__ = ["DocumentTable", "DocumentTaskTable", "document_from_row"]
