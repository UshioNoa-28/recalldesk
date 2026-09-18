"""领域模型测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest import TestCase

from app.domain.documents import Document, DocumentStatus, DocumentTask, DocumentTaskStatus


class DocumentStatusTests(TestCase):
    def test_status_values(self) -> None:
        self.assertEqual("pending", DocumentStatus.PENDING)
        self.assertEqual("success", DocumentStatus.SUCCESS)
        self.assertEqual("failed", DocumentStatus.FAILED)


class DocumentTaskStatusTests(TestCase):
    def test_status_values(self) -> None:
        self.assertEqual("pending", DocumentTaskStatus.PENDING)
        self.assertEqual("queue", DocumentTaskStatus.QUEUE)
        self.assertEqual("success", DocumentTaskStatus.SUCCESS)
        self.assertEqual("failed", DocumentTaskStatus.FAILED)


class DocumentEntityTests(TestCase):
    def test_document_defaults(self) -> None:
        doc = Document(
            id="doc-1",
            name="a.md",
            storage_key="uploads/doc-1",
            size_bytes=3,
            checksum_sha256="abc",
            media_type=None,
            status=DocumentStatus.PENDING,
        )
        self.assertIsNone(doc.chunk_count)
        self.assertIsNone(doc.error_message)
        self.assertIsNone(doc.indexed_at)


class DocumentTaskTests(TestCase):
    def test_entry_fields(self) -> None:
        now = datetime.now(UTC)
        entry = DocumentTask(
            id="task-1",
            document_id="doc-1",
            operation="index",
            status=DocumentTaskStatus.PENDING,
            attempts=0,
            last_error=None,
            created_at=now,
            queued_at=None,
        )
        self.assertEqual("task-1", entry.id)
        self.assertIsNone(entry.queued_at)
        self.assertEqual(0, entry.attempts)


if __name__ == "__main__":
    import unittest

    unittest.main()
