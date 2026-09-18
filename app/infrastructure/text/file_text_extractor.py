"""按文件类型把原始字节读成文本：PDF 走 pypdf 提取文本层，其余按 UTF-8 解码。

放在 infrastructure 而不是 domain：依赖 pypdf，属于外部库适配。
上传与索引两个阶段共用同一套读取逻辑，保证「上传时校验通过的文件，
索引时一定读得出来」。
"""

from __future__ import annotations

import io
from pathlib import PurePosixPath

from pypdf import PdfReader


class PdfExtractionError(ValueError):
    """PDF 解析失败或没有可提取的文本层（如扫描件）。"""


def extract_file_text(*, name: str, content: bytes) -> str:
    """把上传的原始字节读成文本；按文件名后缀分派读取器。"""

    if PurePosixPath(name).suffix.lower() == ".pdf":
        return _extract_pdf_text(content)
    text = content.decode("utf-8-sig")
    if not text.strip():
        raise ValueError("文件内容为空")
    return text


def _extract_pdf_text(content: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(content))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise PdfExtractionError(f"PDF 解析失败: {exc}") from exc
    text = "\n\n".join(pages).strip()
    if not text:
        raise PdfExtractionError("PDF 没有可提取的文本层（可能是扫描件）")
    return text


__all__ = ["PdfExtractionError", "extract_file_text"]
