"""测试用最小 PDF 构造器：手拼 xref，不依赖外部样本文件。"""

from __future__ import annotations


def minimal_pdf(text: str = "Hello PDF") -> bytes:
    """生成合法的单页 PDF（Type1 Helvetica + 一行文本），xref 按实际偏移写。"""

    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        5: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for number in (1, 2, 3, 4, 5):
        offsets[number] = len(out)
        if number == 4:
            out += (
                b"4 0 obj\n<< /Length %d >>\nstream\n" % len(stream)
                + stream
                + b"\nendstream\nendobj\n"
            )
        else:
            out += b"%d 0 obj\n" % number + objects[number] + b"\nendobj\n"

    xref_pos = len(out)
    out += b"xref\n0 6\n0000000000 65535 f \n"
    for number in (1, 2, 3, 4, 5):
        out += b"%010d 00000 n \n" % offsets[number]
    out += b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % xref_pos
    return bytes(out)
