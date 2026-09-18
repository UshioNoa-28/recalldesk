"""Embedding 客户端端口。"""

from __future__ import annotations

from typing import Protocol


class EmbeddingClient(Protocol):
    """把文本变成 dense 向量的能力（实现：llama-index OpenAIEmbedding 等）。"""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量生成向量，返回顺序与输入一致。"""
        ...

    async def embed_one(self, text: str) -> list[float]:
        """单条文本生成向量。"""
        ...


__all__ = ["EmbeddingClient"]
