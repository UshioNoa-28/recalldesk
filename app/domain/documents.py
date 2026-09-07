"""文档域：上传的文档，与它的索引/删除任务（Transactional Outbox）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class DocumentStatus(StrEnum):
    """文档从上传到可检索的生命周期。"""

    PENDING = "pending"   # 上传成功，等待后台索引
    SUCCESS = "success"   # 索引成功，可检索
    FAILED = "failed"     # 重试超限，索引失败


class DocumentTaskStatus(StrEnum):
    """任务投递与执行的生命周期。"""

    PENDING = "pending"   # 已写入，等待发布
    QUEUE = "queue"       # 已投递到 Redis Stream
    SUCCESS = "success"   # 消费处理成功
    FAILED = "failed"     # 重试超限，终态


@dataclass(slots=True)
class Document:
    """一个上传文档的元数据。"""

    id: str
    name: str
    storage_key: str
    size_bytes: int
    checksum_sha256: str
    media_type: str | None
    status: DocumentStatus
    chunk_count: int | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    indexed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DocumentTask:
    """一条任务记录（document_tasks 表的行）。"""

    id: str
    document_id: str
    operation: str
    status: DocumentTaskStatus
    attempts: int
    last_error: str | None
    created_at: datetime
    queued_at: datetime | None


__all__ = ["Document", "DocumentStatus", "DocumentTask", "DocumentTaskStatus"]
