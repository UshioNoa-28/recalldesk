"""LlamaIndexTextSplitter 适配器测试（llama-index-core 离线运行）。"""

from __future__ import annotations

import unittest
from unittest import TestCase

from app.infrastructure.llama_index_text_splitter import LlamaIndexTextSplitter


class LlamaIndexTextSplitterTests(TestCase):
    def test_short_text_single_chunk(self) -> None:
        splitter = LlamaIndexTextSplitter(chunk_size=100, chunk_overlap=10)

        self.assertEqual(["这是一个短句子。"], splitter.split("这是一个短句子。"))

    def test_long_text_produces_multiple_chunks_within_limit(self) -> None:
        text = "".join(f"第{i}句内容需要一些填充字符。" for i in range(60))
        splitter = LlamaIndexTextSplitter(chunk_size=50, chunk_overlap=10)

        chunks = splitter.split(text)

        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 50)

    def test_empty_text_returns_empty(self) -> None:
        splitter = LlamaIndexTextSplitter(chunk_size=50, chunk_overlap=10)

        self.assertEqual([], splitter.split(""))


if __name__ == "__main__":
    unittest.main()
