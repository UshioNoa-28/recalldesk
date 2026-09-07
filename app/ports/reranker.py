"""重排序端口。"""

from __future__ import annotations

from typing import Protocol


class Reranker(Protocol):
    """把候选 chunk 按与查询的相关性重排（实现：Ollama Qwen3-Reranker 生成式重排）。"""

    async def rerank(self, *, query: str, candidates: list[dict], top_k: int) -> list[dict]:
        """输入融合后的候选（含 text 等字段），返回按相关性降序的候选。

        score 会被替换成 rerank 分，其余字段原样保留；返回长度不超过 top_k。
        """
        ...


__all__ = ["Reranker"]
