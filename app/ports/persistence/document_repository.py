"""文档仓储端口。"""

from __future__ import annotations

from typing import Protocol

from app.domain.documents import Document


class DocumentRepository(Protocol):
    """文档元数据持久化能力。"""

    async def add(self, document: Document) -> None:
        """新增一条文档记录（不负责提交事务）。"""
        ...

    async def get(self, document_id: str) -> Document | None:
        """按 ID 查询文档。"""
        ...

    async def list_documents(
        self,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[Document], int]:
        """分页查询，返回 (当前页实体, 总数)。"""
        ...

    async def update(self, document: Document) -> None:
        """把实体最新状态写回数据库（不负责提交事务）。"""
        ...

    async def delete(self, document_id: str) -> None:
        """按 ID 删除文档记录（不负责提交事务）。"""
        ...


__all__ = ["DocumentRepository"]
