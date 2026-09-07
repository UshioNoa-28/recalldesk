"""SplitService 测试：按文档后缀选分块策略（全 fake，不碰真分块器）。"""

from __future__ import annotations

import unittest

from app.application.services.split_service import SplitService


class _RecordingSplitter:
    def __init__(self, tag: str) -> None:
        self.tag = tag
        self.texts: list[str] = []

    def split(self, text: str) -> list[str]:
        self.texts.append(text)
        return [f"{self.tag}: {text}"]


class SplitServiceTests(unittest.TestCase):
    def _service(self) -> tuple[SplitService, _RecordingSplitter, _RecordingSplitter]:
        text = _RecordingSplitter("text")
        csv = _RecordingSplitter("csv")
        return SplitService(text_splitter=text, csv_splitter=csv), text, csv

    def test_csv_goes_to_the_row_splitter(self) -> None:
        service, text, csv = self._service()

        self.assertEqual(["csv: a,b"], service.split("planets.csv", "a,b"))

        self.assertEqual([], text.texts)
        self.assertEqual(["a,b"], csv.texts)

    def test_suffix_match_is_case_insensitive(self) -> None:
        service, _, csv = self._service()

        service.split("PLANETS.CSV", "a,b")

        self.assertEqual(1, len(csv.texts))

    def test_prose_extensions_keep_the_sentence_splitter(self) -> None:
        service, text, csv = self._service()

        for name in ("水果.txt", "README.md", "data.json", "无后缀"):
            service.split(name, "内容")

        self.assertEqual(4, len(text.texts))
        self.assertEqual([], csv.texts)

    def test_last_suffix_wins(self) -> None:
        service, text, csv = self._service()

        service.split("导出.csv.txt", "内容")

        self.assertEqual(1, len(text.texts))
        self.assertEqual([], csv.texts)


if __name__ == "__main__":
    unittest.main()
