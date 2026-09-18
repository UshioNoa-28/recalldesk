"""DocumentService 的上传用例测试（全 fake，不依赖外部服务）。"""

from __future__ import annotations

from unittest import IsolatedAsyncioTestCase

from app.application.services.document.document_service import DocumentService
from app.application.services.document.split_service import SplitService
from app.application.services.search.search_service import SearchService
from app.domain.documents import Document, DocumentStatus
from app.infrastructure.text.csv_text_splitter import CsvTextSplitter
from app.infrastructure.text.llama_index_text_splitter import LlamaIndexTextSplitter
from app.ports.document_file_storage import DocumentFileStorage
from app.ports.persistence.document_repository import DocumentRepository
from app.ports.persistence.document_task_repository import DocumentTaskRepository
from app.ports.persistence.unit_of_work import UnitOfWork
from tests.pdf_fixture import minimal_pdf


class FakeDocumentRepository:
    def __init__(self, fail_on_add: bool = False) -> None:
        self.added: list[Document] = []
        self.fail_on_add = fail_on_add

    async def add(self, document: Document) -> None:
        if self.fail_on_add:
            raise RuntimeError("db down")
        self.added.append(document)

    async def delete(self, document_id: str) -> None:
        self.deleted_ids = getattr(self, "deleted_ids", [])
        self.deleted_ids.append(document_id)
        self.added = [doc for doc in self.added if doc.id != document_id]

    async def get(self, document_id: str) -> Document | None:
        for doc in self.added:
            if doc.id == document_id:
                return doc
        return None

    async def list_documents(self, *, page: int, page_size: int) -> tuple[list[Document], int]:
        return self.added, len(self.added)

    async def update(self, document: Document) -> None:
        return None


class FakeOutboxRepository:
    def __init__(self) -> None:
        self.added: list[tuple[str, str]] = []

    async def add(self, *, document_id: str, operation: str) -> None:
        self.added.append((document_id, operation))

    async def get(self, entry_id: str):
        return None

    async def list_pending(self, *, limit: int):
        return []

    async def mark_queued(self, entry_id: str) -> None:
        return None

    async def mark_success(self, entry_id: str) -> None:
        return None

    async def record_failure(self, entry_id: str, *, error: str) -> None:
        return None

    async def mark_failed(self, entry_id: str) -> None:
        return None


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class FakeFileStorage:
    def __init__(self) -> None:
        self.saved: dict[str, bytes] = {}
        self.deleted: list[str] = []

    def save(self, document_id: str, content: bytes) -> str:
        self.saved[document_id] = content
        return f"uploads/{document_id}"

    def read(self, *, storage_key: str) -> bytes:
        return self.saved[storage_key.rsplit("/", 1)[-1]]

    def delete(self, *, storage_key: str) -> None:
        self.deleted.append(storage_key)


class FakeChunkIndex:
    def __init__(self, chunks: list[dict] | None = None) -> None:
        self.chunks = chunks or []
        self.deleted: list[str] = []

    async def get_document_chunks(self, *, document_id: str) -> list[dict]:
        return self.chunks

    async def delete_document(self, document_id: str) -> None:
        self.deleted.append(document_id)


class FakeSearchService:
    def __init__(self) -> None:
        self.ingested: list[tuple[str, str, str]] = []

    def ingest(self, document_id: str, name: str, text: str) -> None:
        self.ingested.append((document_id, name, text))

    async def search(self, query: str, *, top_k: int | None = None) -> list[dict]:
        return [{"document_name": "x", "score": 1.0, "text": "hit"}]


class FakeEvalRepository:
    """只要 delete_items_referencing_document：删文档时清证据题。"""

    def __init__(self, removed: int = 0) -> None:
        self.removed = removed
        self.purged_for: list[str] = []

    async def delete_items_referencing_document(self, document_id: str) -> int:
        self.purged_for.append(document_id)
        return self.removed


class FakeGraphTaskRepository:
    def __init__(self, latest: dict[str, tuple[str, str | None]] | None = None) -> None:
        self.latest = latest or {}
        self.queued: list[str] = []
        self.actions: list[str] = []

    async def latest_for_document_ids(self, document_ids):
        return {i: self.latest[i] for i in document_ids if i in self.latest}

    async def queue_extraction(self, document_id: str) -> str:
        entry = self.latest.get(document_id)
        if entry and entry[0] in ("pending", "queue"):
            raise ValueError("该文档的图谱抽取正在进行中，等它落定再重跑")
        self.queued.append(document_id)
        action = "requeued" if entry else "created"
        self.actions.append(action)
        return action


def _real_split_service() -> SplitService:
    """真分块器（纯 CPU、快）：上传校验「切得出块」依赖它。"""
    return SplitService(
        text_splitter=LlamaIndexTextSplitter(chunk_size=512, chunk_overlap=64),
        csv_splitter=CsvTextSplitter(chunk_size=512),
    )


def _make_service(
    *,
    repository: DocumentRepository | None = None,
    outbox: DocumentTaskRepository | None = None,
    unit_of_work: UnitOfWork | None = None,
    file_storage: DocumentFileStorage | None = None,
    search_service: SearchService | None = None,
    chunk_index=None,
    split_service: SplitService | None = None,
    eval_repository: FakeEvalRepository | None = None,
    graph_tasks: FakeGraphTaskRepository | None = None,
    graph_enabled: bool = False,
) -> (
    tuple[DocumentService, FakeUnitOfWork, FakeFileStorage, FakeOutboxRepository, FakeSearchService]
):
    uow = unit_of_work or FakeUnitOfWork()
    storage = file_storage or FakeFileStorage()
    outbox = outbox or FakeOutboxRepository()
    search = search_service or FakeSearchService()
    vectors = chunk_index or FakeChunkIndex()
    service = DocumentService(
        repository=repository or FakeDocumentRepository(),
        unit_of_work=uow,
        file_storage=storage,
        outbox=outbox,
        split_service=split_service or _real_split_service(),
        search_service=search,
        chunk_index=vectors,
        eval_repository=eval_repository or FakeEvalRepository(),
        graph_tasks=graph_tasks or FakeGraphTaskRepository(),
        graph_enabled=graph_enabled,
    )
    return service, uow, storage, outbox, search


class DocumentServiceIngestTests(IsolatedAsyncioTestCase):
    """上传用例：文档 + 任务同事务提交，数据库失败时补偿删除本地文件。"""

    async def test_ingest_writes_document_and_task_then_commits(self) -> None:
        service, uow, storage, outbox, search = _make_service()

        document = await service.ingest(
            name="notes.txt",
            content=b"hello world",
            media_type="text/plain",
        )

        self.assertEqual(DocumentStatus.PENDING, document.status)
        self.assertEqual(1, uow.commits)
        self.assertEqual(("notes.txt", b"hello world"), (document.name, storage.saved[document.id]))
        self.assertEqual([(document.id, "index")], outbox.added)
        # 上传阶段不应该直接索引
        self.assertEqual([], search.ingested)

    async def test_ingest_deletes_file_when_database_fails(self) -> None:
        repository = FakeDocumentRepository(fail_on_add=True)
        service, uow, storage, outbox, _ = _make_service(repository=repository)

        with self.assertRaises(RuntimeError):
            await service.ingest(name="bad.txt", content=b"x", media_type=None)

        self.assertEqual(1, len(storage.deleted))  # 补偿删除了本地文件
        self.assertEqual(0, uow.commits)
        self.assertEqual([], outbox.added)

    async def test_search_delegates_to_search_service(self) -> None:
        service, _, _, _, _ = _make_service()

        hits = await service.search("query", top_k=3)

        self.assertEqual([{"document_name": "x", "score": 1.0, "text": "hit"}], hits)

    async def test_ingest_rejects_non_utf8_content(self) -> None:
        service, _, storage, outbox, _ = _make_service()

        with self.assertRaises(UnicodeDecodeError):
            await service.ingest(name="bad.txt", content=b"\xff\xfe\x00", media_type=None)

        self.assertEqual({}, storage.saved)      # 校验失败，不落盘
        self.assertEqual([], outbox.added)

    async def test_ingest_rejects_empty_content(self) -> None:
        service, _, storage, outbox, _ = _make_service()

        with self.assertRaises(ValueError):
            await service.ingest(name="empty.txt", content=b"   \n", media_type=None)

        self.assertEqual({}, storage.saved)
        self.assertEqual([], outbox.added)

    async def test_ingest_rejects_content_that_cannot_be_split(self) -> None:
        """只有表头行的 CSV 切不出块：入口就 400，而不是让 worker 白跑 10 次退避。"""
        service, _, storage, outbox, _ = _make_service()

        with self.assertRaises(ValueError) as exc:
            await service.ingest(name="table.csv", content=b"id,name\n", media_type="text/csv")

        self.assertIn("切不出", str(exc.exception))
        self.assertEqual({}, storage.saved)
        self.assertEqual([], outbox.added)

    async def test_ingest_accepts_pdf(self) -> None:
        service, _, storage, outbox, _ = _make_service()

        document = await service.ingest(
            name="paper.pdf",
            content=minimal_pdf("Extracted text"),
            media_type="application/pdf",
        )

        self.assertEqual(DocumentStatus.PENDING, document.status)
        self.assertEqual(minimal_pdf("Extracted text"), storage.saved[document.id])
        self.assertEqual([(document.id, "index")], outbox.added)

    async def test_ingest_rejects_pdf_without_text_layer(self) -> None:
        service, _, storage, outbox, _ = _make_service()

        with self.assertRaises(ValueError):
            await service.ingest(
                name="scan.pdf", content=minimal_pdf(""), media_type="application/pdf"
            )

        self.assertEqual({}, storage.saved)  # 校验失败，不落盘
        self.assertEqual([], outbox.added)

    async def test_get_returns_uploaded_document(self) -> None:
        service, _, _, _, _ = _make_service()
        created = await service.ingest(name="a.md", content=b"hello", media_type=None)

        loaded = await service.get(created.id)

        self.assertEqual(created.id, loaded.id)
        self.assertEqual("a.md", loaded.name)

    async def test_get_missing_raises_key_error(self) -> None:
        service, _, _, _, _ = _make_service()

        with self.assertRaises(KeyError):
            await service.get("no-such-doc")

    async def test_list_documents_returns_mapped_page(self) -> None:
        service, _, _, _, _ = _make_service()
        await service.ingest(name="a.md", content=b"a", media_type=None)
        await service.ingest(name="b.md", content=b"b", media_type=None)

        result = await service.list_documents(page=1, page_size=10)

        self.assertEqual(2, result["total"])
        self.assertEqual(2, len(result["items"]))
        self.assertIn("status", result["items"][0])
        self.assertEqual("pending", result["items"][0]["status"])

    async def test_commit_failure_deletes_file(self) -> None:
        class FailingUow(FakeUnitOfWork):
            async def commit(self) -> None:
                raise RuntimeError("commit failed")

        service, _, storage, _outbox, _ = _make_service(unit_of_work=FailingUow())

        with self.assertRaises(RuntimeError):
            await service.ingest(name="a.md", content=b"a", media_type=None)

        self.assertEqual(1, len(storage.deleted))  # 补偿删除本地文件


class DocumentServiceChunksContentDeleteTests(IsolatedAsyncioTestCase):
    async def _service_with_doc(self):
        vectors = FakeChunkIndex(chunks=[
            {"point_id": "p-1", "chunk_index": 0, "chunk_count": 2, "text": "第一段"},
            {"point_id": "p-2", "chunk_index": 1, "chunk_count": 2, "text": "第二段"},
        ])
        repo = FakeDocumentRepository()
        service, uow, storage, _outbox, _ = _make_service(
            repository=repo, chunk_index=vectors
        )
        document = await service.ingest(
            name="a.txt", content="第一段。第二段".encode(), media_type="text/plain"
        )
        return service, repo, vectors, storage, uow, document

    async def test_chunks_returns_structure(self) -> None:
        service, _, _, _, _, document = await self._service_with_doc()

        result = await service.chunks(document.id)

        self.assertEqual(document.id, result["document_id"])
        self.assertEqual(2, result["total_chunks"])
        self.assertEqual(["p-1", "p-2"], [c["point_id"] for c in result["chunks"]])
        self.assertEqual(["第一段", "第二段"], [c["text"] for c in result["chunks"]])

    async def test_chunks_missing_document_raises(self) -> None:
        service, *_ = await self._service_with_doc()

        with self.assertRaises(KeyError):
            await service.chunks("missing")

    async def test_content_returns_name_and_text(self) -> None:
        service, _, _, _, _, document = await self._service_with_doc()

        name, text = await service.content(document.id)

        self.assertEqual("a.txt", name)
        self.assertEqual("第一段。第二段", text)

    async def test_content_returns_extracted_pdf_text(self) -> None:
        repo = FakeDocumentRepository()
        service, _, _, _, _ = _make_service(repository=repo)
        document = await service.ingest(
            name="paper.pdf",
            content=minimal_pdf("PDF body"),
            media_type="application/pdf",
        )

        name, text = await service.content(document.id)

        self.assertEqual("paper.pdf", name)
        self.assertEqual("PDF body", text)

    async def test_content_missing_document_raises(self) -> None:
        service, *_ = await self._service_with_doc()

        with self.assertRaises(KeyError):
            await service.content("missing")

    async def test_delete_defers_vector_cleanup_to_the_worker(self) -> None:
        """请求内不碰 Neo4j：删索引块是 outbox 里的一条 delete 任务。

        同事务里还要先把把这篇文档当证据/答案引用的题清掉：证据文档的
        FK 只会删证据行、留下半截题，必须显式purge。
        """

        vectors = FakeChunkIndex()
        repo = FakeDocumentRepository()
        evals = FakeEvalRepository(removed=2)
        service, uow, storage, outbox, _ = _make_service(
            repository=repo, chunk_index=vectors, eval_repository=evals
        )
        document = await service.ingest(
            name="a.txt", content="第一段。第二段".encode(), media_type="text/plain"
        )

        await service.delete(document.id)

        self.assertEqual([], vectors.deleted)
        self.assertEqual([document.id], evals.purged_for)  # purge 与删行同事务
        self.assertEqual(
            [(document.id, "index"), (document.id, "delete")], outbox.added
        )
        self.assertEqual([document.id], repo.deleted_ids)
        self.assertEqual(2, uow.commits)  # 上传一次、删除一次
        self.assertEqual([f"uploads/{document.id}"], storage.deleted)

    async def test_delete_missing_document_raises(self) -> None:
        service, *_ = await self._service_with_doc()

        with self.assertRaises(KeyError):
            await service.delete("missing")


class DocumentServiceReindexTests(IsolatedAsyncioTestCase):
    """重新索引：FAILED / SUCCESS 重置后重投任务，PENDING 拒绝叠任务。"""

    async def _uploaded(self, status: DocumentStatus):
        repo = FakeDocumentRepository()
        service, uow, _, outbox, _ = _make_service(repository=repo)
        document = await service.ingest(name="a.txt", content=b"hello world", media_type=None)
        document.status = status
        document.chunk_count = 3
        document.error_message = "boom" if status is DocumentStatus.FAILED else None
        return service, uow, outbox, document

    async def test_reindex_failed_document_resets_and_enqueues(self) -> None:
        service, uow, outbox, document = await self._uploaded(DocumentStatus.FAILED)

        result = await service.reindex(document.id)

        self.assertEqual(DocumentStatus.PENDING, result.status)
        self.assertIsNone(result.chunk_count)
        self.assertIsNone(result.error_message)
        self.assertIsNone(result.indexed_at)
        self.assertEqual([(document.id, "index"), (document.id, "index")], outbox.added)
        self.assertEqual(2, uow.commits)

    async def test_reindex_success_document_is_allowed(self) -> None:
        # 换 CHUNK_SIZE / 嵌入模型后要整篇重建：健康的文档也允许重切
        service, uow, outbox, document = await self._uploaded(DocumentStatus.SUCCESS)

        result = await service.reindex(document.id)

        self.assertEqual(DocumentStatus.PENDING, result.status)
        self.assertEqual(2, len(outbox.added))  # 上传一条 + reindex 一条
        self.assertEqual(2, uow.commits)

    async def test_reindex_pending_document_is_rejected(self) -> None:
        service, uow, outbox, document = await self._uploaded(DocumentStatus.PENDING)

        with self.assertRaises(ValueError):
            await service.reindex(document.id)

        self.assertEqual(1, len(outbox.added))  # 只有上传那一条
        self.assertEqual(1, uow.commits)

    async def test_reindex_missing_document_raises_key_error(self) -> None:
        service, *_ = _make_service()

        with self.assertRaises(KeyError):
            await service.reindex("missing")


class GraphStatusAndRerunTests(IsolatedAsyncioTestCase):
    async def _indexed(self, *, graph_tasks=None, graph_enabled=True):
        graph = graph_tasks or FakeGraphTaskRepository()
        service, uow, *_ = _make_service(graph_tasks=graph, graph_enabled=graph_enabled)
        document = await service.ingest(
            name="a.txt", content="第一段。第二段".encode(), media_type="text/plain"
        )
        document.status = DocumentStatus.SUCCESS
        return service, uow, graph, document

    async def test_detail_exposes_graph_status(self) -> None:
        service, _, graph, document = await self._indexed(
            graph_tasks=FakeGraphTaskRepository()
        )
        graph.latest[document.id] = ("failed", "ConnectionError: llm down")

        detail = await service.detail(document.id)

        self.assertEqual("failed", detail["graph"]["status"])
        self.assertIn("llm down", detail["graph"]["error"])

    async def test_graph_disabled_yields_null_status(self) -> None:
        service, _, _, document = await self._indexed(graph_enabled=False)

        detail = await service.detail(document.id)

        self.assertIsNone(detail["graph"])

    async def test_rerun_graph_rejects_disabled_and_unindexed(self) -> None:
        service, _, _, document = await self._indexed(graph_enabled=False)
        with self.assertRaises(ValueError):
            await service.rerun_graph(document.id)

        service2, _, _, document2 = await self._indexed()
        document2.status = DocumentStatus.PENDING
        with self.assertRaises(ValueError):
            await service2.rerun_graph(document2.id)

    async def test_rerun_graph_resets_failed_and_commits(self) -> None:
        service, uow, graph, document = await self._indexed(
            graph_tasks=FakeGraphTaskRepository()
        )
        graph.latest[document.id] = ("failed", "boom")
        commits_before = uow.commits

        result = await service.rerun_graph(document.id)

        self.assertEqual("requeued", result["action"])
        self.assertEqual([document.id], graph.queued)
        self.assertEqual(commits_before + 1, uow.commits)

    async def test_rerun_graph_refuses_inflight(self) -> None:
        service, _, graph, document = await self._indexed(
            graph_tasks=FakeGraphTaskRepository()
        )
        graph.latest[document.id] = ("queue", None)

        with self.assertRaises(ValueError):
            await service.rerun_graph(document.id)
        self.assertEqual([], graph.queued)


if __name__ == "__main__":
    import unittest

    unittest.main()
