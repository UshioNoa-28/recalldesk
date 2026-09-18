"""CSV 分块器：按「行」装填，每块自带表头。"""

from __future__ import annotations

from app.ports.text_splitter import TextSplitter


class CsvTextSplitter(TextSplitter):
    """一行是一条记录，所以只按行装箱：既不劈开一行，也不跨块重复行。

    与句子分块器不同，这里没有 overlap：表头已经每块自带，再重复数据行只会让
    同一条记录被命中两遍。第一行按表头对待（无表头的表会被当成一行表头，
    代价只是那条记录不再单独成块）。
    """

    def __init__(self, *, chunk_size: int) -> None:
        self._chunk_size = chunk_size

    def split(self, text: str) -> list[str]:
        rows = _logical_rows(text)
        if len(rows) < 2:
            return []

        header, body = rows[0], rows[1:]
        # 表头和它的换行先占掉额度，装填时就不用再算
        budget = self._chunk_size - len(header) - 1

        chunks: list[str] = []
        batch: list[str] = []
        used = 0
        for row in body:
            if batch and used + len(row) + 1 > budget:
                chunks.append("\n".join([header, *batch]))
                batch, used = [], 0
            batch.append(row)
            used += len(row) + 1
        if batch:
            chunks.append("\n".join([header, *batch]))
        return chunks


def _logical_rows(text: str) -> list[str]:
    """物理行合成逻辑行：被引号包住的换行属于同一个字段。"""

    rows: list[str] = []
    for line in text.splitlines():
        if rows and rows[-1].count('"') % 2:
            rows[-1] += "\n" + line  # 上一行引号没闭合，这是它的续行
        else:
            rows.append(line)
    return [row for row in rows if row.strip()]


__all__ = ["CsvTextSplitter"]
