"""文档业务编排：上传、列表、详情、检索。"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid

from app.application.services.document.split_service import SplitService
from app.application.services.search.search_service import SearchService
from app.domain.documents import Document, DocumentStatus
from app.infrastructure.text.file_text_extractor import extract_file_text
from app.ports.chunk_index import ChunkIndex
from app.ports.document_file_storage import DocumentFileStorage
from app.ports.persistence.document_repository import DocumentRepository
from app.ports.persistence.document_task_repository import DocumentTaskRepository
from app.ports.persistence.eval_repository import EvalRepository
from app.ports.persistence.graph_task_repository import GraphTaskRepository
from app.ports.persistence.unit_of_work import UnitOfWork

logger = logging.getLogger(__name__)


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
        chunk_index: ChunkIndex,
        eval_repository: EvalRepository,
        graph_tasks: GraphTaskRepository,
        graph_enabled: bool = False,
    ) -> None:
        self._repository = repository
        self._unit_of_work = unit_of_work
        self._file_storage = file_storage
        self._outbox = outbox
        self._split_service = split_service
        self._search_service = search_service
        self._index = chunk_index
        self._evals = eval_repository
        self._graph_tasks = graph_tasks
        self._graph_enabled = graph_enabled

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
        graphs = await self._graph_states([item.id for item in items])
        return {
            "items": [{**self._to_dict(item), "graph": graphs.get(item.id)} for item in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def detail(self, document_id: str) -> dict:
        """文档详情：元数据 + 图谱状态（GET /documents/{id} 的唯一出口）。"""

        document = await self.get(document_id)
        graphs = await self._graph_states([document_id])
        return {**self._to_dict(document), "graph": graphs.get(document_id)}

    async def _graph_states(self, ids: list[str]) -> dict[str, dict]:
        """图谱状态按文档独立暴露，不掺进 documents.status——那是索引链路的生命周期，
        图是另一条链路的；关掉图谱时干脆不给字段，前端见缺省就不渲染角标。"""

        if not self._graph_enabled or not ids:
            return {}
        latest = await self._graph_tasks.latest_for_document_ids(ids)
        result: dict[str, dict] = {}
        for doc_id in ids:
            entry = latest.get(doc_id)
            if entry is None:
                result[doc_id] = {"status": "none", "error": None}
            else:
                status, error = entry
                result[doc_id] = {"status": status, "error": error if status == "failed" else None}
        return result

    async def rerun_graph(self, document_id: str) -> dict:
        """手动重跑图谱抽取：failed 复位、success 重抽（整篇替换幂等）、在途拒绝。"""

        if not self._graph_enabled:
            raise ValueError("图谱链路未启用（GRAPH_ENABLED=false）")
        document = await self.get(document_id)
        if document.status is not DocumentStatus.SUCCESS:
            raise ValueError("文档尚未索引成功，先等索引完成再抽取图谱")
        action = await self._graph_tasks.queue_extraction(document_id)
        await self._unit_of_work.commit()
        return {"document_id": document.id, "name": document.name, "action": action, "queued": True}

    async def search(self, query: str, *, top_k: int | None = None) -> list[dict]:
        return await self._search_service.search(query, top_k=top_k)

    async def chunks(self, document_id: str) -> dict:
        """列出文档的全部分块（向量库为准）。"""

        await self.get(document_id)  # 不存在 -> KeyError(404)
        chunks = await self._index.get_document_chunks(document_id=document_id)
        return {"document_id": document_id, "total_chunks": len(chunks), "chunks": chunks}

    async def content(self, document_id: str) -> tuple[str, str]:
        """读取原始文档文本，返回 (文档名, 文本)。"""

        document = await self.get(document_id)
        raw = await asyncio.to_thread(
            self._file_storage.read, storage_key=document.storage_key
        )
        return document.name, extract_file_text(name=document.name, content=raw)

    async def reindex(self, document_id: str) -> Document:
        """重新索引：FAILED 修好依赖后救回来，SUCCESS 换分块/嵌入参数后重建。

        一个 PG 事务里重置文档状态 + 写 index 任务，之后与首次索引走完全相同的
        路（publisher 投递 -> consumer 建向量）。PENDING（正在处理）拒绝，免得
        手滑叠任务；底层 upsert 先清旧点再写新点，重复任务本身也无害。
        """

        document = await self.get(document_id)
        if document.status is DocumentStatus.PENDING:
            raise ValueError("文档正在处理中，完成或失败后再重新索引")
        document.status = DocumentStatus.PENDING
        document.chunk_count = None
        document.error_message = None
        document.indexed_at = None
        await self._repository.update(document)
        await self._outbox.add(document_id=document.id, operation="index")
        await self._unit_of_work.commit()
        return document

    async def delete(self, document_id: str) -> None:
        """删除文档：一个 PG 事务（清引用题 + documents 行 + 删除任务）-> 原始文件 best-effort。

        索引块不在请求内同步删。Neo4j 不在 PG 事务里，「先删块、后 commit」失败时留下的是
        更坏的那种状态：文档行还在、索引块没了，检索再也命中不到却仍能下载原文件。
        改成往 outbox 写一条 operation='delete' 与删行同事务提交，索引 worker 幂等删。

        题目引用没有外键兜底（0013 起 items 不挂 documents）：「文档消失 =>
        引用它的题消失」全靠这里在同一事务里先 purge——delete_items_referencing_document
        清掉把它当证据的全部题目（证据平权），这些题的 eval_run_items 历史与未发出
        任务随题目级联一起走；evidence→documents 的 RESTRICT 外键是忘 purge 时
        的有声保险丝（documents 行会删不动、事务回滚）。两个 worker 都已容忍
        任务/条目消失，在途消息安全。
        剩下的窗口只有一个：文档正在索引时删它，embedding 结束后的回写会留下孤儿点
        —— 下次按同一 document_id 删除即可收敛。
        """

        document = await self.get(document_id)
        removed = await self._evals.delete_items_referencing_document(document_id)
        if removed:
            logger.info("删文档连带删除引用它的评测题: doc=%s items=%d", document_id, removed)
        await self._outbox.add(document_id=document_id, operation="delete")
        await self._repository.delete(document_id)
        await self._unit_of_work.commit()
        self._delete_file_best_effort(document.storage_key)

    def _delete_file_best_effort(self, storage_key: str) -> None:
        try:
            self._file_storage.delete(storage_key=storage_key)
        except Exception:
            # 补偿失败只记日志，不影响主流程：文件是本地盘上的孤儿，
            # 静默吞掉反而会让磁盘无声涨起来
            logger.warning(
                "补偿删除文件失败（孤儿文件留在磁盘上）: key=%s", storage_key, exc_info=True
            )

    @staticmethod
    def _to_dict(document: Document) -> dict:
        return {
            "id": document.id,
            "name": document.name,
            "status": document.status,
            "chunk_count": document.chunk_count,
            "created_at": document.created_at.isoformat() if document.created_at else None,
            "indexed_at": document.indexed_at.isoformat() if document.indexed_at else None,
            "error_message": document.error_message,
        }


__all__ = ["DocumentService"]
