"""图谱第三路召回：query → 实体链接 → k 跳扩展 → 支撑 chunk 候选。

纪律：图频道只递提案、不当法官——输出与 dense/sparse 同形状的命中列表，
进同一个 RRF；任何异常都在 SearchService 侧被降级成空列表（本频道
自身不吞异常，方便测试与日志定位）。
"""

from __future__ import annotations

from app.ports.graph_repository import GraphRepository

# 入口链接的宽度：hints 与全文兜底各自最多取几个种子
LINK_LIMIT = 5  # 种子预算：三路各取 5，合并去重后仍截 5


class GraphRecallChannel:
    """SearchService 的可选第三通道；graph_enabled=false 时压根不会构建。"""

    def __init__(
        self,
        store: GraphRepository,
        *,
        hops: int = 2,
        candidates: int = 20,
        link_min_score: float = 0.72,
    ) -> None:
        self._store = store
        self._hops = hops
        self._candidates = candidates
        self._link_min_score = link_min_score

    async def _select_seeds(
        self,
        query: str,
        *,
        entities: list[str] | None = None,
        query_vector: list[float] | None = None,
    ) -> list[str]:
        """三路合并选种子:exact(别名表) 全文(BM25) 向量近邻"""

        seeds: list[str] = []

        def absorb(found: list[str]) -> None:
            """自动去重 这里按的是调用顺序 别名精确匹配 BM25 最后才是 dense vector匹配"""
            for norm in found:
                if norm not in seeds:
                    seeds.append(norm)

        if entities:
            absorb(await self._store.link_by_names(list(entities), limit=LINK_LIMIT))
            # 别名找entity 如果llm改写携带了改写后的别名的话
        absorb(await self._store.link_by_text(query, limit=LINK_LIMIT))
        if query_vector:
            absorb(
                await self._store.link_by_vector(
                    query_vector, limit=LINK_LIMIT, min_score=self._link_min_score
                )
            )
        return seeds[:LINK_LIMIT] # 不超过总的limit

    async def recall(
        self,
        query: str,
        *,
        entities: list[str] | None = None,
        query_vector: list[float] | None = None,
    ) -> list[dict]:
        """query → 种子链接 → k 跳扩展，输出第三路 chunk 候选。

        空种子的短路交给 store（expand_from 自己守门），这里不再重复检查。
        """

        seeds = await self._select_seeds(
            query, entities=entities, query_vector=query_vector
        )
        return await self._store.expand_from(seeds, hops=self._hops, limit=self._candidates)


__all__ = ["GraphRecallChannel"]
