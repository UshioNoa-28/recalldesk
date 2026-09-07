"""DocumentTaskConsumer 处理任务的测试（patch 掉具体仓储，用 fake）。"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from app.application.services.consume.document_task_consumer import DocumentTaskConsumer
from app.application.services.indexing_service import EmptyContentError
from app.domain.documents import Document, DocumentStatus, DocumentTask, DocumentTaskStatus
from settings import settings
from tests.pdf_fixture import minimal_pdf


def _document(name: str = "notes.md") -> Document:
    return Document(
        id="doc-1",
        name=name,
        storage_key="uploads/doc-1",
        size_bytes=10,
        checksum_sha256="0" * 64,
        media_type="text/markdown",
        status=DocumentStatus.PENDING,
    )


def _entry(attempts: int = 0) -> DocumentTask:
    return DocumentTask(
        id="task-1",
        document_id="doc-1",
        operation="index",
        status=DocumentTaskStatus.QUEUE,
        attempts=attempts,
        last_error=None,
        created_at=datetime.now(UTC),
        queued_at=datetime.now(UTC),
    )


class FakeSession:
    def __init__(self, commit_error: Exception | None = None) -> None:
        self.commit_error = commit_error
        self.commits = 0

    async def commit(self) -> None:
        if self.commit_error is not None:
            raise self.commit_error
        self.commits += 1


class _FakeSessionFactory:
    """返回一个假的异步上下文，yield 一个假 session。"""

    def __init__(self, session: FakeSession) -> None:
        self._session = session

    def __call__(self):
        return _FakeSessionContext(self._session)


class _FakeSessionContext:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> FakeSession:
        return self._session

    async def __aexit__(self, *args) -> None:
        return None


class FakeDocumentRepository:
    instances: list[FakeDocumentRepository] = []
    document: Document | None = _document()  # 类级配置；None 表示文档不存在

    def __init__(self, session: FakeSession) -> None:
        self.session = session
        self.document = type(self).document
        self.updated: list[Document] = []
        FakeDocumentRepository.instances.append(self)

    async def get(self, document_id: str) -> Document | None:
        return self.document if self.document and self.document.id == document_id else None

    async def update(self, document: Document) -> None:
        self.updated.append(document)


class FakeOutboxRepository:
    instances: list[FakeOutboxRepository] = []
    attempts_after_failure: int = 0  # 类级配置，供测试控制 get() 返回的 attempts

    def __init__(self, session: FakeSession) -> None:
        self.session = session
        self.success_entries: list[str] = []
        self.failed_entries: list[str] = []
        self.recorded_failures: list[str] = []
        FakeOutboxRepository.instances.append(self)

    async def get(self, entry_id: str) -> DocumentTask | None:
        return _entry(attempts=type(self).attempts_after_failure)

    async def mark_success(self, entry_id: str) -> None:
        self.success_entries.append(entry_id)

    async def record_failure(self, entry_id: str, *, error: str) -> None:
        self.recorded_failures.append(entry_id)

    async def mark_failed(self, entry_id: str) -> None:
        self.failed_entries.append(entry_id)


class FakeFileStorage:
    def __init__(self, content: bytes = "文件内容".encode()) -> None:
        self.content = content

    def read(self, *, storage_key: str) -> bytes:
        return self.content

    def delete(self, *, storage_key: str) -> None:
        return None


class SucceedingIndexingService:
    def __init__(self) -> None:
        self.ingested: list[tuple[str, str, str]] = []
        self.deleted: list[str] = []

    async def ingest(self, document_id: str, name: str, text: str) -> int:
        self.ingested.append((document_id, name, text))
        return 5

    async def delete(self, document_id: str) -> None:
        self.deleted.append(document_id)


class FailingIndexingService:
    async def ingest(self, document_id: str, name: str, text: str) -> int:
        raise RuntimeError("embedding down")

    async def delete(self, document_id: str) -> None:
        raise RuntimeError("qdrant down")


class EmptyContentIndexingService:
    async def ingest(self, document_id: str, name: str, text: str) -> int:
        raise EmptyContentError("文档没有可索引的内容")

    async def delete(self, document_id: str) -> None:
        raise RuntimeError("qdrant down")


class FakeQueue:
    def __init__(self) -> None:
        self.acked: list[str] = []
        self.claimed: list[tuple[str, dict]] = []
        self.claim_error: Exception | None = None

    async def enqueue(self, *, task_id: str, document_id: str, operation: str) -> str:
        return "1-0"

    async def ensure_consumer_group(self) -> None:
        return None

    async def read_new(
        self, *, consumer_name: str, count: int, block_ms: int
    ) -> list[tuple[str, dict]]:
        return []

    async def ack(self, message_id: str) -> None:
        self.acked.append(message_id)

    async def claim_orphans(self, *, consumer_name: str, count: int) -> list[tuple[str, dict]]:
        if self.claim_error is not None:
            raise self.claim_error
        return self.claimed


def _make_consumer(
    indexing_service,
    queue: FakeQueue | None = None,
    session: FakeSession | None = None,
    file_storage: FakeFileStorage | None = None,
) -> tuple[DocumentTaskConsumer, FakeQueue]:
    queue = queue or FakeQueue()
    consumer = DocumentTaskConsumer(
        queue=queue,
        session_factory=_FakeSessionFactory(session or FakeSession()),
        file_storage=file_storage or FakeFileStorage(),
        indexing_service=indexing_service,
    )
    return consumer, queue


class DocumentTaskConsumerHandleTaskTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        FakeDocumentRepository.instances.clear()
        FakeOutboxRepository.instances.clear()
        FakeDocumentRepository.document = _document()      # 恢复默认：文档存在
        FakeOutboxRepository.attempts_after_failure = 0

    @patch(
        "app.application.services.consume.document_task_consumer.SqlAlchemyDocumentRepository",
        FakeDocumentRepository,
    )
    @patch(
        "app.application.services.consume.document_task_consumer.SqlAlchemyDocumentTaskRepository",
        FakeOutboxRepository,
    )
    async def test_success_marks_task_and_document_success(self) -> None:
        consumer, _ = _make_consumer(SucceedingIndexingService())

        await consumer._handle_task(task_id="task-1", document_id="doc-1", operation="index")

        outbox = FakeOutboxRepository.instances[0]
        doc_repo = FakeDocumentRepository.instances[0]
        self.assertEqual(["task-1"], outbox.success_entries)
        updated = doc_repo.updated[-1]
        self.assertEqual(DocumentStatus.SUCCESS, updated.status)
        self.assertEqual(5, updated.chunk_count)
        self.assertIsNotNone(updated.indexed_at)

    @patch(
        "app.application.services.consume.document_task_consumer.SqlAlchemyDocumentRepository",
        FakeDocumentRepository,
    )
    @patch(
        "app.application.services.consume.document_task_consumer.SqlAlchemyDocumentTaskRepository",
        FakeOutboxRepository,
    )
    async def test_pdf_task_extracts_text_before_indexing(self) -> None:
        FakeDocumentRepository.document = _document(name="paper.pdf")
        indexing = SucceedingIndexingService()
        consumer, _ = _make_consumer(
            indexing, file_storage=FakeFileStorage(content=minimal_pdf("PDF body"))
        )

        await consumer._handle_task(task_id="task-1", document_id="doc-1", operation="index")

        self.assertEqual([("doc-1", "paper.pdf", "PDF body")], indexing.ingested)

    @patch(
        "app.application.services.consume.document_task_consumer.SqlAlchemyDocumentRepository",
        FakeDocumentRepository,
    )
    @patch(
        "app.application.services.consume.document_task_consumer.SqlAlchemyDocumentTaskRepository",
        FakeOutboxRepository,
    )
    async def test_failure_below_max_records_failure_and_returns(self) -> None:
        FakeOutboxRepository.attempts_after_failure = settings.task_max_attempts - 1
        consumer, _ = _make_consumer(FailingIndexingService())

        # 业务失败在 _handle_task 内落库并正常返回（由调用方 ACK）
        await consumer._handle_task(task_id="task-1", document_id="doc-1", operation="index")

        outbox = FakeOutboxRepository.instances[0]
        self.assertEqual(["task-1"], outbox.recorded_failures)
        self.assertEqual([], outbox.failed_entries)  # 未超限，不标终态

    @patch(
        "app.application.services.consume.document_task_consumer.SqlAlchemyDocumentRepository",
        FakeDocumentRepository,
    )
    @patch(
        "app.application.services.consume.document_task_consumer.SqlAlchemyDocumentTaskRepository",
        FakeOutboxRepository,
    )
    async def test_failure_at_max_marks_task_and_document_failed(self) -> None:
        FakeOutboxRepository.attempts_after_failure = settings.task_max_attempts
        consumer, _ = _make_consumer(FailingIndexingService())

        await consumer._handle_task(task_id="task-1", document_id="doc-1", operation="index")

        doc_repo = FakeDocumentRepository.instances[0]
        outbox = FakeOutboxRepository.instances[0]
        self.assertEqual(["task-1"], outbox.failed_entries)
        self.assertEqual(DocumentStatus.FAILED, doc_repo.updated[-1].status)

    @patch(
        "app.application.services.consume.document_task_consumer.SqlAlchemyDocumentRepository",
        FakeDocumentRepository,
    )
    @patch(
        "app.application.services.consume.document_task_consumer.SqlAlchemyDocumentTaskRepository",
        FakeOutboxRepository,
    )
    async def test_empty_content_fails_immediately_without_backoff(self) -> None:
        """切不出分块是内容问题：直接终态，不进指数退避（不用白跑 10 次）。"""
        consumer, _ = _make_consumer(EmptyContentIndexingService())

        await consumer._handle_task(task_id="task-1", document_id="doc-1", operation="index")

        outbox = FakeOutboxRepository.instances[0]
        doc_repo = FakeDocumentRepository.instances[0]
        self.assertEqual(["task-1"], outbox.failed_entries)
        self.assertEqual([], outbox.recorded_failures)  # 没走退避路径
        updated = doc_repo.updated[-1]
        self.assertEqual(DocumentStatus.FAILED, updated.status)
        self.assertIn("EmptyContentError", updated.error_message)

    @patch(
        "app.application.services.consume.document_task_consumer.SqlAlchemyDocumentRepository",
        FakeDocumentRepository,
    )
    @patch(
        "app.application.services.consume.document_task_consumer.SqlAlchemyDocumentTaskRepository",
        FakeOutboxRepository,
    )
    async def test_missing_document_marks_task_success(self) -> None:
        FakeDocumentRepository.document = None
        consumer, _ = _make_consumer(SucceedingIndexingService())

        await consumer._handle_task(task_id="task-1", document_id="doc-1", operation="index")

        outbox = FakeOutboxRepository.instances[0]
        self.assertEqual(["task-1"], outbox.success_entries)  # 幂等：文档没了直接算成功

    @patch(
        "app.application.services.consume.document_task_consumer.SqlAlchemyDocumentRepository",
        FakeDocumentRepository,
    )
    @patch(
        "app.application.services.consume.document_task_consumer.SqlAlchemyDocumentTaskRepository",
        FakeOutboxRepository,
    )
    async def test_delete_drops_vectors_without_needing_the_document_row(self) -> None:
        """删除任务的 documents 行注定已经没了：那不是跳过的理由。"""

        FakeDocumentRepository.document = None
        indexing = SucceedingIndexingService()
        consumer, _ = _make_consumer(indexing)

        await consumer._handle_task(task_id="task-1", document_id="doc-1", operation="delete")

        self.assertEqual(["doc-1"], indexing.deleted)
        self.assertEqual([], indexing.ingested)
        self.assertEqual(["task-1"], FakeOutboxRepository.instances[0].success_entries)


class DocumentTaskConsumerMessageTests(IsolatedAsyncioTestCase):
    """_process_single_message：字段校验和 ACK 行为。"""

    async def test_missing_fields_acks_and_skips(self) -> None:
        consumer, queue = _make_consumer(SucceedingIndexingService())

        await consumer._process_single_message("msg-1", {"document_id": "doc-1"})  # 缺 task_id

        self.assertEqual(["msg-1"], queue.acked)

    async def test_valid_message_processes_and_acks(self) -> None:
        consumer, queue = _make_consumer(SucceedingIndexingService())

        with patch.object(consumer, "_handle_task", AsyncMock()) as handle:
            await consumer._process_single_message(
                "msg-1",
                {"task_id": "task-1", "document_id": "doc-1"},
            )

        handle.assert_awaited_once_with(
            task_id="task-1", document_id="doc-1", operation="index"
        )  # 老消息没有 operation 字段：按索引处理
        self.assertEqual(["msg-1"], queue.acked)

    async def test_delete_operation_is_forwarded(self) -> None:
        consumer, queue = _make_consumer(SucceedingIndexingService())

        with patch.object(consumer, "_handle_task", AsyncMock()) as handle:
            await consumer._process_single_message(
                "msg-1",
                {"task_id": "task-1", "document_id": "doc-1", "operation": "delete"},
            )

        handle.assert_awaited_once_with(
            task_id="task-1", document_id="doc-1", operation="delete"
        )
        self.assertEqual(["msg-1"], queue.acked)

    @patch(
        "app.application.services.consume.document_task_consumer.SqlAlchemyDocumentRepository",
        FakeDocumentRepository,
    )
    @patch(
        "app.application.services.consume.document_task_consumer.SqlAlchemyDocumentTaskRepository",
        FakeOutboxRepository,
    )
    async def test_business_failure_commits_and_acks(self) -> None:
        consumer, queue = _make_consumer(FailingIndexingService())

        # 业务失败：落库后正常返回 → 消息 ACK（重试走 publisher 重投）
        await consumer._process_single_message(
            "msg-1",
            {"task_id": "task-1", "document_id": "doc-1"},
        )

        outbox = FakeOutboxRepository.instances[-1]
        self.assertEqual(["task-1"], outbox.recorded_failures)
        self.assertEqual(["msg-1"], queue.acked)

    async def test_commit_failure_does_not_ack(self) -> None:
        session = FakeSession(commit_error=RuntimeError("db gone"))
        consumer, queue = _make_consumer(SucceedingIndexingService(), session=session)

        await consumer._process_single_message(
            "msg-1",
            {"task_id": "task-1", "document_id": "doc-1"},
        )

        self.assertEqual([], queue.acked)  # 不 ACK，留 XAUTOCLAIM 恢复

    @patch(
        "app.application.services.consume.document_task_consumer.SqlAlchemyDocumentRepository",
        FakeDocumentRepository,
    )
    @patch(
        "app.application.services.consume.document_task_consumer.SqlAlchemyDocumentTaskRepository",
        FakeOutboxRepository,
    )
    async def test_delete_failure_does_not_record_or_ack(self) -> None:
        """Qdrant 抖动对删除任务不是业务失败：没有文档行可记失败，留给孤儿认领重投。"""

        consumer, queue = _make_consumer(FailingIndexingService())

        await consumer._process_single_message(
            "msg-1",
            {"task_id": "task-1", "document_id": "doc-1", "operation": "delete"},
        )

        outbox = FakeOutboxRepository.instances[-1]
        self.assertEqual([], outbox.success_entries)
        self.assertEqual([], outbox.recorded_failures)
        self.assertEqual([], queue.acked)


class DocumentTaskConsumerOrphanTests(IsolatedAsyncioTestCase):
    """孤儿任务认领的容错与处理。"""

    async def test_claim_orphans_failure_is_non_fatal(self) -> None:
        queue = FakeQueue()
        queue.claim_error = ConnectionError("redis down")
        consumer, _ = _make_consumer(SucceedingIndexingService(), queue=queue)

        await consumer._claim_and_process_orphans()  # 不应抛异常

    async def test_claimed_orphans_are_processed(self) -> None:
        queue = FakeQueue()
        queue.claimed = [("msg-9", {"task_id": "task-9", "document_id": "doc-9"})]
        consumer, _ = _make_consumer(SucceedingIndexingService(), queue=queue)

        with patch.object(consumer, "_process_single_message", AsyncMock()) as process:
            await consumer._claim_and_process_orphans()

        process.assert_awaited_once_with("msg-9", {"task_id": "task-9", "document_id": "doc-9"})


if __name__ == "__main__":
    import unittest

    unittest.main()
