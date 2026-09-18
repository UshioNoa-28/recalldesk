"""Lucene 全文查询的输入消毒（chunk 与 entity 两个索引共用）。"""

from __future__ import annotations

import re

_SPECIAL = re.compile(r"[^\w]+", re.UNICODE)


def fulltext_query(query_text: str) -> str:
    """把自由文本转成安全的全文查询：切词 → 剥非词字符 → 逐词包引号做 OR。

    不消毒会把输入里的 + - && || ! ( ) { } [ ] ^ " ~ * ? : \\ /
    当 Lucene 语法解析，轻则报错重则语义全变。
    """

    terms = [_SPECIAL.sub("", token) for token in query_text.split()]
    terms = [token for token in terms if token]
    if not terms:
        return ""
    return " ".join(f'"{token}"' for token in terms)


__all__ = ["fulltext_query"]
