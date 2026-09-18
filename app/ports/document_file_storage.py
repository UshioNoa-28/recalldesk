"""文件存储端口。"""

from __future__ import annotations

from typing import Protocol


class DocumentFileStorage(Protocol):
    """原始文件保存与读取能力。"""

    def save(self, document_id: str, content: bytes) -> str:
        """保存文件并返回 storage_key。"""
        ...

    def read(self, *, storage_key: str) -> bytes:
        """按 storage_key 读取原始文件。"""
        ...

    def delete(self, *, storage_key: str) -> None:
        """删除原始文件；文件不存在也视为成功（幂等）。"""
        ...


__all__ = ["DocumentFileStorage"]
