"""llama-index OpenAIEmbedding 适配器：把框架实现挂到 EmbeddingClient 端口上。

底层的批量、重试、OpenAI 兼容适配（含 Ollama）都由 llama-index 处理；
异步走 BaseEmbedding 原生的 aget_text_embedding_batch。
"""

from __future__ import annotations

from llama_index.embeddings.openai import OpenAIEmbedding

from app.ports.embedding_client import EmbeddingClient


class LlamaIndexEmbeddingClient(EmbeddingClient):
    def __init__(self, *, model_name: str, api_base: str, api_key: str) -> None:
        self._embed = OpenAIEmbedding(
            model_name=model_name,
            api_base=api_base,
            api_key=api_key,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await self._embed.aget_text_embedding_batch(texts)

    async def embed_one(self, text: str) -> list[float]:
        return await self._embed.aget_text_embedding(text)


__all__ = ["LlamaIndexEmbeddingClient"]
