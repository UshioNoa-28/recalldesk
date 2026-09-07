"""分块服务：按文档类型选出该用哪种切法。"""

from __future__ import annotations

from pathlib import PurePosixPath

from app.ports.text_splitter import TextSplitter


class SplitService:
    """文本的自然切割单位随类型而变：正文按句，CSV 按行（一行就是一条记录）。

    用按句的尺子切 CSV 会把一条记录劈成两半、表头只留在第一块里，所以这里按后缀选。
    """

    def __init__(
        self, *, text_splitter: TextSplitter, csv_splitter: TextSplitter
    ) -> None:
        self._text_splitter = text_splitter
        self._csv_splitter = csv_splitter

    def split(self, name: str, text: str) -> list[str]:
        splitter = (
            self._csv_splitter
            if PurePosixPath(name).suffix.lower() == ".csv"
            else self._text_splitter
        )
        return splitter.split(text)


__all__ = ["SplitService"]
