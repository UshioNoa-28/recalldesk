"""本地文件存储测试（临时目录，不碰项目 data/）。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.infrastructure.local_file_storage import LocalFileStorage


class LocalFileStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.storage = LocalFileStorage(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_save_read_delete_roundtrip(self) -> None:
        storage_key = self.storage.save("doc-1", b"hello")

        self.assertEqual("uploads/doc-1", storage_key)
        self.assertEqual(b"hello", self.storage.read(storage_key=storage_key))

        self.storage.delete(storage_key=storage_key)
        self.assertFalse((self.root / storage_key).exists())

    def test_delete_missing_file_is_idempotent(self) -> None:
        self.storage.delete(storage_key="uploads/nope")  # 不抛异常


if __name__ == "__main__":
    unittest.main()
