"""llama-index SentenceSplitter 适配器：把框架实现挂到 TextSplitter 端口上。

llama-index 在本项目里的使用边界：只做分块（以及将来的元数据 extractor），
存储、检索、融合都不经过它。

语义与原实现保持一致：
- chunk_size 按「字符数」计：tokenizer 传 list(text)（中文一字一 token）；
- 按中英文句末标点切句（chunking_tokenizer_fn）；
- 相邻块带 chunk_overlap 重叠。
"""

from __future__ import annotations

import re

from llama_index.core.node_parser import SentenceSplitter

from app.ports.text_splitter import TextSplitter

_SENTENCE_PATTERN = re.compile(r"(?<=[。！？.!?])\s*")


def _split_sentences(text: str) -> list[str]:
    """按中英文句末标点切句，标点跟随前一句。"""

    return [part for part in _SENTENCE_PATTERN.split(text) if part.strip()]


class LlamaIndexTextSplitter(TextSplitter):
    def __init__(self, *, chunk_size: int, chunk_overlap: int) -> None:
        self._splitter = SentenceSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            tokenizer=lambda text: list(text),
            chunking_tokenizer_fn=_split_sentences,
        )

    def split(self, text: str) -> list[str]:
        return [chunk for chunk in self._splitter.split_text(text) if chunk.strip()]


__all__ = ["LlamaIndexTextSplitter"]
