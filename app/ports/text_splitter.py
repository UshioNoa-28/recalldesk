"""文本分块端口。"""

from __future__ import annotations

from typing import Protocol


class TextSplitter(Protocol):
    """把长文本切成 chunk 列表的能力（具体分块策略由实现决定）。"""

    def split(self, text: str) -> list[str]:
        """返回按原文顺序排列的非空 chunk 列表。"""
        ...


__all__ = ["TextSplitter"]
