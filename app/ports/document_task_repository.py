"""任务发件箱（Transactional Outbox）端口。"""

from __future__ import annotations

from typing import Protocol

from app.domain.documents import DocumentTask


class DocumentTaskRepository(Protocol):
    """任务表的读写能力。"""

    async def add(self, *, document_id: str, operation: str) -> None:
        """向当前事务追加一条 PENDING 任务。"""
        ...

    async def get(self, entry_id: str) -> DocumentTask | None:
        """按 ID 查任务。"""
        ...

    async def list_pending(self, *, limit: int) -> list[DocumentTask]:
        """读取 PENDING 任务，按创建时间升序。"""
        ...

    async def mark_queued(self, entry_id: str) -> None:
        """标记任务已投递到 Redis Stream（PENDING -> QUEUE）。"""
        ...

    async def mark_success(self, entry_id: str) -> None:
        """标记任务消费处理成功（QUEUE -> SUCCESS）。"""
        ...

    async def record_failure(self, entry_id: str, *, error: str) -> None:
        """记录一次失败：attempts+1、状态回 PENDING（指数退避等重投），
        超限终态由调用方随后用 mark_failed 覆盖。"""
        ...

    async def mark_failed(self, entry_id: str) -> None:
        """把任务标记为终态 FAILED。"""
        ...


__all__ = ["DocumentTaskRepository"]
