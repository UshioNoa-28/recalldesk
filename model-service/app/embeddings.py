from __future__ import annotations

import httpx

from app.config import Settings
from app.errors import UpstreamError


def _brief(body: str) -> str:
    text = (body or "").strip()
    return text if len(text) <= 300 else text[:300]


async def embed_texts(
    client: httpx.AsyncClient, settings: Settings, texts: list[str]
) -> list[list[float]]:
    """按输入顺序返回向量；顺序与条数都是对 Java 的硬承诺。"""
    if not texts:
        return []

    vectors: list[list[float]] = []
    batch_size = max(1, settings.embedding_batch_size)
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        payload = {"model": settings.embedding_model, "input": batch}
        try:
            response = await client.post(
                f"{settings.ollama_root}/v1/embeddings",
                json=payload,
                timeout=settings.embedding_timeout_seconds,
            )
        except httpx.RequestError as exc:
            raise UpstreamError(f"embedding 请求失败: {exc}") from exc

        if response.status_code >= 400:
            raise UpstreamError(
                f"embedding HTTP {response.status_code}: {_brief(response.text)}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise UpstreamError("embedding 响应不是 JSON") from exc
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise UpstreamError("embedding 响应缺少 data 数组")
        if len(data) != len(batch):
            raise UpstreamError(
                f"embedding 返回 {len(data)} 条，请求了 {len(batch)} 条"
            )

        # 协议没承诺顺序，按 index 归位；缺 index 时按响应位置
        ordered = sorted(
            enumerate(data), key=lambda pair: int(pair[1].get("index", pair[0]))
        )
        for _, item in ordered:
            vector = item.get("embedding")
            if not isinstance(vector, list):
                raise UpstreamError("embedding 响应缺少向量")
            if len(vector) != settings.embedding_dim:
                raise UpstreamError(
                    f"embedding 维度 {len(vector)} 与配置 {settings.embedding_dim} 不一致"
                )
            vectors.append([float(value) for value in vector])

    return vectors
