"""知识图谱存储端口（现由 Neo4j 实现）：实体/关系/证据的存取与检索。

图形状（:Chunk 节点由 ChunkIndex 负责建，这里只管图语义）：

    (:Entity)-[:REL {type, evidence}]-(:Entity)
    # evidence = ["doc_id:chunk_index", ...]，断言级出处挂在关系边上

三条纪律：
- 实体以 name_norm 归一键去重；MERGE 命中旧实体时，新表面形与别名做并集
  （apple 和 Apples 即使分裂成两次抽取，链接面也会互相认识）；
- 每条 REL 边的 evidence 是"哪些 chunk 说过这条关系"的坐标数组——同一事实
  被多篇/多块挺过时并存不抢位，重抽取 = 剔本篇前缀再回写，掏空的边删除，
  孤儿实体顺手清扫（没抽进任何三元组的实体不留）——图永远是可重建派生物；
- 检索原语返回与 ChunkIndex 同款的命中 dict（含 text），
  SearchService 的第三路直接可用；融合键 point_id 口径一致。

写入载荷用 domain 的 GraphEntity/GraphTriple 类型（键名即 Cypher 参数名，
adapter 里 asdict 直转）；Cypher 只准出现在实现里。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.domain.graph import GraphEntity, GraphTriple


class GraphRepository(Protocol):
    """实体链接、k 跳扩展与整篇文档的图写入/清理。"""

    async def ensure_indexes(self) -> None:
        """幂等建 Entity 索引（name_norm 约束 / 全文 / 向量），组装期 fail fast。"""
        ...

    async def upsert_document_graph(
        self,
        *,
        document_id: str,
        entities: Sequence[GraphEntity],
        triples: Sequence[GraphTriple],
    ) -> int:
        """整篇替换该文档的图贡献，返回写入实体数。

        复活守卫：本篇在 ChunkIndex 里已无 chunk（被删/重建中）时整篇放弃，
        返回 0——在途抽取的迟到回写不许凭空造僵尸子图。
        """
        ...

    async def link_by_names(self, names: list[str], *, limit: int) -> list[str]:
        """按名字/别名精确链接实体（query rewrite 给出的 entities 走这里）。"""
        ...

    async def link_by_text(self, query_text: str, *, limit: int) -> list[str]:
        """按全文检索把整段查询词链接到实体（词面兜底）。"""
        ...

    async def link_by_vector(
        self, vector: list[float], *, limit: int, min_score: float
    ) -> list[str]:
        """按向量近邻链接实体（LightRAG 式：不赌字面，apples 也能找到 apple）。

        min_score 是余弦下限，防"永远能凑满 top-k"的假种子。
        """
        ...

    async def expand_from(self, seeds: list[str], *, hops: int, limit: int) -> list[dict]:
        """从种子实体出发 k 跳扩展，路径边 evidence 指向的 chunk 变成第三路候选。

        返回与 ChunkIndex 检索同款的命中 dict（point_id/document_id/
        chunk_index/text/document_name/chunk_count/score），
        score 为递减的通道内名次分，只服务 RRF 排序。
        """
        ...

    async def delete_document_graph(self, document_id: str) -> None:
        """从所有 REL 边的 evidence 里减掉本篇坐标，掏空的边删除，
        顺带清扫孤儿实体（幂等）。"""
        ...

    # ---- 浏览原语（Focus+Expand 的取数，图谱浏览器专用，检索链路不吃） ----

    async def neighborhood(self, seeds: list[str], *, hops: int, limit: int) -> dict:
        """种子实体 + ≤hops 跳邻居的子图切片（Bloom 式展开的取数）。

        邻居预算：跳数升序、同跳按"通往中心的最强路径上的证据数"降序取
        前 limit——hub 的海量弱邻居会被截断，中心节点永远保留。
        返回 {"nodes": [{name_norm,name,type,hops,path_evidence}],
              "edges": [{src,dst,type,evidence:[point_id,...]}]}，
        边只收两端都在节点集内的（无向语义，src/dst 存的是存储方向）。
        """
        ...

    async def search_entities(self, query: str, *, limit: int = 8) -> list[dict]:
        """按名称精准/前缀/别名/包含四档优先级检索候选（补全搜索）。

        空 query 时按图连通度 (degree) 与证据量返回中心种子。
        """
        ...


__all__ = ["GraphRepository"]
