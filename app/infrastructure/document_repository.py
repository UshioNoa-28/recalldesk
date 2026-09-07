"""文档仓储的 SQLAlchemy 实现。"""

from __future__ import annotations

from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.documents import Document
from app.infrastructure.tables import DocumentTable, document_from_row
from app.ports.document_repository import DocumentRepository


class SqlAlchemyDocumentRepository(DocumentRepository):
    """使用共享 AsyncSession 持久化文档元数据。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, document: Document) -> None:
        self._session.add(
            DocumentTable(
                id=document.id,
                name=document.name,
                storage_key=document.storage_key,
                size_bytes=document.size_bytes,
                checksum_sha256=document.checksum_sha256,
                media_type=document.media_type,
                status=document.status.value,
                chunk_count=document.chunk_count,
                error_message=document.error_message,
                indexed_at=document.indexed_at,
            )
        )

    async def get(self, document_id: str) -> Document | None:
        row = await self._session.get(DocumentTable, document_id)
        return None if row is None else document_from_row(row)

    async def list_documents(
        self,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[Document], int]:
        total = await self._session.scalar(select(func.count()).select_from(DocumentTable))
        rows = (
            await self._session.scalars(
                select(DocumentTable)
                .order_by(DocumentTable.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return [document_from_row(row) for row in rows], int(total or 0)

    async def update(self, document: Document) -> None:
        row = await self._session.get(DocumentTable, document.id)
        if row is None:
            raise KeyError(document.id)
        row.name = document.name
        row.storage_key = document.storage_key
        row.size_bytes = document.size_bytes
        row.checksum_sha256 = document.checksum_sha256
        row.media_type = document.media_type
        row.status = document.status.value
        row.chunk_count = document.chunk_count
        row.error_message = document.error_message
        row.indexed_at = document.indexed_at

    async def delete(self, document_id: str) -> None:
        await self._session.execute(
            sql_delete(DocumentTable).where(DocumentTable.id == document_id)
        )


__all__ = ["SqlAlchemyDocumentRepository"]
