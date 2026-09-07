"""CsvTextSplitter 测试：按行装箱、每块自带表头（离线）。"""

from __future__ import annotations

import unittest

from app.infrastructure.csv_text_splitter import CsvTextSplitter

HEADER = "method,number,orbital_period,mass,distance,year"


def _rows(count: int) -> list[str]:
    return [
        f"Radial Velocity,{i},{100 + i}.0,0.{i:02d},77.4,200{i % 10}"
        for i in range(count)
    ]


class CsvTextSplitterTests(unittest.TestCase):
    def test_header_is_repeated_in_every_chunk(self) -> None:
        splitter = CsvTextSplitter(chunk_size=200)

        chunks = splitter.split("\n".join([HEADER, *_rows(20)]))

        self.assertGreater(len(chunks), 1)
        self.assertLess(len(chunks), 20)  # 确实在装箱，不是一块一行
        for chunk in chunks:
            lines = chunk.splitlines()
            self.assertEqual(HEADER, lines[0])
            self.assertLessEqual(len(chunk), 200)

    def test_rows_survive_intact_and_in_order(self) -> None:
        rows = _rows(20)
        splitter = CsvTextSplitter(chunk_size=200)

        chunks = splitter.split("\n".join([HEADER, *rows]))

        # 一条记录不许被劈开，也不许在两块里各出现一次
        self.assertEqual(rows, [line for c in chunks for line in c.splitlines()[1:]])

    def test_row_wider_than_budget_gets_its_own_chunk(self) -> None:
        wide = "备注" * 100
        splitter = CsvTextSplitter(chunk_size=60)

        chunks = splitter.split("\n".join([HEADER, "a,1", wide, "b,2"]))

        self.assertEqual(3, len(chunks))
        self.assertEqual([wide], chunks[1].splitlines()[1:])

    def test_quoted_field_containing_newline_stays_one_row(self) -> None:
        row = 'Direct Imaging,1,"多行\n字段",10,20,2004'
        splitter = CsvTextSplitter(chunk_size=1000)

        chunks = splitter.split("\n".join([HEADER, row, "Transit,2,3,4,5,2005"]))

        self.assertEqual(1, len(chunks))
        self.assertIn(row, chunks[0])

    def test_blank_lines_are_dropped(self) -> None:
        rows = _rows(3)
        splitter = CsvTextSplitter(chunk_size=1000)

        chunks = splitter.split("\n".join([HEADER, "", *rows, "", ""]))

        self.assertEqual([HEADER, *rows], chunks[0].splitlines())

    def test_header_only_file_has_nothing_to_index(self) -> None:
        splitter = CsvTextSplitter(chunk_size=200)

        self.assertEqual([], splitter.split(HEADER))


if __name__ == "__main__":
    unittest.main()
