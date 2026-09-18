"""图浏览器编排服务：实体搜索 + Focus+Expand 邻域取数（Bloom 式只读）。

纪律：service 编排、repository 只递原语——搜索走名称补全（精准>前缀>
别名>包含，四档优先级在 store 的 Cypher 里定），与检索路的语义链接
（GraphRecallChannel._select_seeds）刻意分开：浏览要找"你输入的那个东西"，
检索要找"和查询相关的东西"，两种需求不该共用一条路。
"""

from __future__ import annotations

import logging

from app.application.services.graph.graph_channel import GraphRecallChannel
from app.ports.graph_repository import GraphRepository
from app.ports.model_clients.embedding_client import EmbeddingClient

logger = logging.getLogger(__name__)


class GraphExplorerService:
    def __init__(
        self,
        *,
        store: GraphRepository,
        channel: GraphRecallChannel,
        embedding_client: EmbeddingClient | None = None,
    ) -> None:
        self._store = store
        self._channel = channel
        self._embedding = embedding_client

    async def search_entities(self, query: str, *, limit: int = 8) -> list[dict]:
        """按前缀搜索entity 用于搜索栏展示"""
        return await self._store.search_entities(query, limit=limit)

    async def neighborhood(self, name_norm: str, *, hops: int = 1, limit: int = 60) -> dict:
        """以单个实体为中心的 ≤hops 跳子图切片；实体不存在返回空 nodes。"""

        return await self._store.neighborhood([name_norm], hops=hops, limit=limit)


__all__ = ["GraphExplorerService"]
