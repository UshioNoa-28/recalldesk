"""文档业务编排：上传、列表、详情、检索。"""

from __future__ import annotations

import asyncio
import hashlib
import uuid

from app.application.services.search_service import SearchService
from app.application.services.split_service import SplitService
from app.domain.documents import Document, DocumentStatus
from app.infrastructure.file_text_extractor import extract_file_text
from app.ports.document_file_storage import DocumentFileStorage
from app.ports.document_repository import DocumentRepository
from app.ports.document_task_repository import DocumentTaskRepository
from app.ports.unit_of_work import UnitOfWork
from app.ports.vector_repository import VectorRepository


class DocumentService:
    """文档用例编排。

    上传时先校验「文本读得出来、也切得出块」，然后存本地文件 -> 一个 PG 事务
    写 documents + document_tasks -> 返回 PENDING。索引交给后台 DocumentTaskPublisher/
    DocumentTaskConsumer，入口把内容性问题挡掉，worker 就不用为它们空跑退避。
    """

    def __init__(
        self,
        *,
        repository: DocumentRepository,
        unit_of_work: UnitOfWork,
        file_storage: DocumentFileStorage,
        outbox: DocumentTaskRepository,
        split_service: SplitService,
        search_service: SearchService,
        vector_repository: VectorRepository,
    ) -> None:
        self._repository = repository
        self._unit_of_work = unit_of_work
        self._file_storage = file_storage
        self._outbox = outbox
        self._split_service = split_service
        self._search_service = search_service
        self._vector_repository = vector_repository

    async def ingest(self, *, name: str, content: bytes, media_type: str | None) -> Document:
        """保存文件 + 写文档和任务（同一事务），返回 PENDING 文档。"""

        # 只做校验：可读性（UTF-8 / PDF 文本层）+ 切得出至少一块（如只有表头
        # 行的 CSV 切不出块，在这里 400，而不是等 worker 重试 10 次）。
        # pypdf 解析和分块都是同步 CPU 活：丢线程池跑，别把 API 事件循环堵住
        #（否则传个大 PDF 时 /health 都会跟着卡，healthcheck 会超时）
        def _validate_content() -> None:
            text = extract_file_text(name=name, content=content)
            if not self._split_service.split(name, text):
                raise ValueError("文档内容切不出任何分块，无法索引")

        await asyncio.to_thread(_validate_content)
        document_id = str(uuid.uuid4())
        storage_key = self._file_storage.save(document_id, content)

        document = Document(
            id=document_id,
            name=name,
            storage_key=storage_key,
            size_bytes=len(content),
            checksum_sha256=hashlib.sha256(content).hexdigest(),
            media_type=media_type,
            status=DocumentStatus.PENDING,
        )

        try:
            await self._repository.add(document)
            # 任务与文档同事务提交：要么都有，要么都回滚
            await self._outbox.add(document_id=document.id, operation="index")
            await self._unit_of_work.commit()
        except Exception:
            # 补偿：数据库失败时，把已保存的本地文件删掉，避免孤儿文件
            self._delete_file_best_effort(storage_key)
            raise
        return document

    async def get(self, document_id: str) -> Document:
        document = await self._repository.get(document_id)
        if document is None:
            raise KeyError(document_id)
        return document

    async def list_documents(self, *, page: int, page_size: int) -> dict:
        items, total = await self._repository.list_documents(page=page, page_size=page_size)
        return {
            "items": [self._to_dict(item) for item in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def search(self, query: str, *, top_k: int) -> list[dict]:
        return await self._search_service.search(query, top_k=top_k)

    async def chunks(self, document_id: str) -> dict:
        """列出文档的全部分块（向量库为准）。"""

        await self.get(document_id)  # 不存在 -> KeyError(404)
        chunks = await self._vector_repository.get_document_chunks(document_id=document_id)
        return {"document_id": document_id, "total_chunks": len(chunks), "chunks": chunks}

    async def content(self, document_id: str) -> tuple[str, str]:
        """读取原始文档文本，返回 (文档名, 文本)。"""

        document = await self.get(document_id)
        raw = await asyncio.to_thread(
            self._file_storage.read, storage_key=document.storage_key
        )
        return document.name, extract_file_text(name=document.name, content=raw)

    async def delete(self, document_id: str) -> None:
        """删除文档：一个 PG 事务（documents 行 + 删除任务）-> 原始文件 best-effort。

        向量不在请求内同步删。Qdrant 没有事务，「先删向量、后 commit」失败时留下的是
        更坏的那种状态：文档行还在、向量没了，检索再也命中不到却仍能下载原文件。
        改成往 outbox 写一条 operation='delete' 与删行同事务提交，索引 worker 幂等删。

        eval_testset_items 对 documents 是 CASCADE，所以引用它的题目、以及这些题目
        未发出的出题任务一起走；两个 worker 都已容忍任务/条目消失，在途消息安全。
        剩下的窗口只有一个：文档正在索引时删它，embedding 结束后的回写会留下孤儿点
        —— 下次按同一 document_id 删除即可收敛。
        """

        document = await self.get(document_id)
        await self._outbox.add(document_id=document_id, operation="delete")
        await self._repository.delete(document_id)
        await self._unit_of_work.commit()
        self._delete_file_best_effort(document.storage_key)

    def _delete_file_best_effort(self, storage_key: str) -> None:
        try:
            self._file_storage.delete(storage_key=storage_key)
        except Exception:
            pass  # 补偿失败只记日志，不影响主异常

    @staticmethod
    def _to_dict(document: Document) -> dict:
        return {
            "id": document.id,
            "name": document.name,
            "status": document.status.value,
            "chunk_count": document.chunk_count,
            "created_at": document.created_at.isoformat() if document.created_at else None,
            "indexed_at": document.indexed_at.isoformat() if document.indexed_at else None,
            "error_message": document.error_message,
        }


__all__ = ["DocumentService"]
