"""file_text_extractor 单元测试：手搓最小 PDF，验证提取与分派。"""

from __future__ import annotations

import unittest

from app.infrastructure.file_text_extractor import PdfExtractionError, extract_file_text
from tests.pdf_fixture import minimal_pdf


class ExtractFileTextTests(unittest.TestCase):
    def test_pdf_returns_extracted_text(self) -> None:
        self.assertEqual("Hello PDF", extract_file_text(name="a.pdf", content=minimal_pdf()))

    def test_pdf_suffix_is_case_insensitive(self) -> None:
        self.assertEqual("Hello PDF", extract_file_text(name="A.PDF", content=minimal_pdf()))

    def test_pdf_without_text_layer_raises(self) -> None:
        with self.assertRaisesRegex(PdfExtractionError, "文本层"):
            extract_file_text(name="scan.pdf", content=minimal_pdf(""))

    def test_broken_pdf_raises(self) -> None:
        with self.assertRaises(PdfExtractionError):
            extract_file_text(name="bad.pdf", content=b"not a pdf at all")

    def test_text_file_still_decodes_utf8(self) -> None:
        self.assertEqual("你好", extract_file_text(name="a.txt", content="你好".encode()))

    def test_text_file_strips_bom(self) -> None:
        self.assertEqual("hello", extract_file_text(name="a.txt", content=b"\xef\xbb\xbfhello"))

    def test_text_file_empty_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "为空"):
            extract_file_text(name="a.txt", content=b"  \n ")

    def test_text_file_non_utf8_raises(self) -> None:
        with self.assertRaises(UnicodeDecodeError):
            extract_file_text(name="a.txt", content=b"\xff\xfe\x00")


if __name__ == "__main__":
    unittest.main()
