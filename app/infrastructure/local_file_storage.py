"""本地文件存储实现。"""

from __future__ import annotations

from pathlib import Path

from app.ports.document_file_storage import DocumentFileStorage


class LocalFileStorage(DocumentFileStorage):
    """用内部 ID 作为文件名，保存到 data/uploads/。"""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._upload_dir = self._root / "uploads"

    def save(self, document_id: str, content: bytes) -> str:
        self._upload_dir.mkdir(parents=True, exist_ok=True)
        (self._upload_dir / document_id).write_bytes(content)
        return f"uploads/{document_id}"

    def read(self, *, storage_key: str) -> bytes:
        return (self._root / storage_key).read_bytes()

    def delete(self, *, storage_key: str) -> None:
        (self._root / storage_key).unlink(missing_ok=True)


__all__ = ["LocalFileStorage"]
