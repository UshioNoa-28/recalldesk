"""DocumentService 的上传用例测试（全 fake，不依赖外部服务）。"""

from __future__ import annotations

from unittest import IsolatedAsyncioTestCase

from app.application.services.document_service import DocumentService
from app.application.services.search_service import SearchService
from app.application.services.split_service import SplitService
from app.domain.documents import Document, DocumentStatus
from app.infrastructure.csv_text_splitter import CsvTextSplitter
from app.infrastructure.llama_index_text_splitter import LlamaIndexTextSplitter
from app.ports.document_file_storage import DocumentFileStorage
from app.ports.document_repository import DocumentRepository
from app.ports.document_task_repository import DocumentTaskRepository
from app.ports.unit_of_work import UnitOfWork
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


class FakeVectorRepository:
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
    vector_repository=None,
    split_service: SplitService | None = None,
) -> (
    tuple[DocumentService, FakeUnitOfWork, FakeFileStorage, FakeOutboxRepository, FakeSearchService]
):
    uow = unit_of_work or FakeUnitOfWork()
    storage = file_storage or FakeFileStorage()
    outbox = outbox or FakeOutboxRepository()
    search = search_service or FakeSearchService()
    vectors = vector_repository or FakeVectorRepository()
    service = DocumentService(
        repository=repository or FakeDocumentRepository(),
        unit_of_work=uow,
        file_storage=storage,
        outbox=outbox,
        split_service=split_service or _real_split_service(),
        search_service=search,
        vector_repository=vectors,
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
        vectors = FakeVectorRepository(chunks=[
            {"point_id": "p-1", "chunk_index": 0, "chunk_count": 2, "text": "第一段"},
            {"point_id": "p-2", "chunk_index": 1, "chunk_count": 2, "text": "第二段"},
        ])
        repo = FakeDocumentRepository()
        service, uow, storage, _outbox, _ = _make_service(
            repository=repo, vector_repository=vectors
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
        """请求内不碰 Qdrant：删向量是 outbox 里的一条 delete 任务。"""

        vectors = FakeVectorRepository()
        repo = FakeDocumentRepository()
        service, uow, storage, outbox, _ = _make_service(
            repository=repo, vector_repository=vectors
        )
        document = await service.ingest(
            name="a.txt", content="第一段。第二段".encode(), media_type="text/plain"
        )

        await service.delete(document.id)

        self.assertEqual([], vectors.deleted)
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


if __name__ == "__main__":
    import unittest

    unittest.main()
