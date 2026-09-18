"""GraphRepository 的 Neo4j 实现：实体/关系/证据的存与查。

图形状：
    (:Entity {name_norm 唯一})-[:REL {type, evidence}]-(:Entity)
证据挂在 REL 边上：`evidence` 是 point_id 口径的字符串数组（"doc_id:chunk_index"），
"苹果能补铁"被 3 个 chunk 说过就是 3 个元素——一条规范边收齐所有出处，
不再有 (:Chunk)-[:SUPPORTS]->(:Entity) 那种"证据指向实体"的实体级支撑
（2026-09-15 拍板：断言级证据才有检索价值，实体只是索引锚点）。
重抽取 = 剔掉本篇前缀的证据再回写（其他文档的条目不动），掏空的边删除，
孤儿实体顺手清扫；图库整个删掉可从原始文件重灌（派生物纪律）。
迁移注记：旧格式边（单值 doc_id、无 evidence）会在任意一次 rebuild 中被
掏空删除，全库 rerun 一遍自然换新，无需数据兼容。

Cypher 书写纪律：本文件与 chunk_index.py 是全项目仅有的两处 Cypher 聚集地，
写子句之间一律用 WITH 屏障（DETACH DELETE 后必须 WITH 才能接 UNWIND）；
驱动把查询文本钉成 LiteralString（防注入警铃），只有插了运行时值
（维度/分析器/跳数）的查询需要 cast(LiteralString, ...) 放行——插值全是
内部计算值，零外部输入（Query() 帮不上忙，它的 text 参数同样要字面量）。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import asdict
from typing import LiteralString, cast

from neo4j import AsyncDriver

from app.domain.graph import GraphEntity, GraphTriple
from app.infrastructure.neo4j.lucene import fulltext_query
from app.ports.graph_repository import GraphRepository

logger = logging.getLogger(__name__)

ENTITY_TEXT_INDEX = "entity_text"
ENTITY_VECTOR_INDEX = "entity_embedding"
ENTITY_KEY_CONSTRAINT = "entity_name_norm"


class Neo4jGraphRepository(GraphRepository):
    """实体链接 + k 跳扩展 + 整篇文档的图写入/清理。"""

    def __init__(
        self,
        driver: AsyncDriver,
        *,
        embedding_dim: int,
        analyzer: str = "cjk",
        database: str = "neo4j",
    ) -> None:
        self._driver = driver
        self._dim = embedding_dim
        self._analyzer = analyzer
        self._database = database

    # ---- 组装期 ----

    async def ensure_indexes(self) -> None:
        await self._driver.execute_query(
            f"CREATE CONSTRAINT {ENTITY_KEY_CONSTRAINT} IF NOT EXISTS "
            "FOR (e:Entity) REQUIRE e.name_norm IS UNIQUE",
            database_=self._database,
        )
        await self._driver.execute_query(
            cast(
                "LiteralString",
                f"CREATE FULLTEXT INDEX {ENTITY_TEXT_INDEX} IF NOT EXISTS "
                "FOR (e:Entity) ON EACH [e.name, e.aliases, e.description] "
                f"OPTIONS {{indexConfig: {{`fulltext.analyzer`: '{self._analyzer}'}}}}",
            ),
            database_=self._database,
        )
        # 已存在的向量索引：比对维度（IF NOT EXISTS 对旧维度静默跳过是坑）
        rows = await self._driver.execute_query(
            "SHOW VECTOR INDEXES YIELD name, options WHERE name = $name "
            "RETURN options.indexConfig AS cfg",
            name=ENTITY_VECTOR_INDEX,
            database_=self._database,
        )
        for record in rows.records:
            cfg = record["cfg"] or {}
            configured = int(cfg.get("vector.dimensions", self._dim))
            if configured != self._dim:
                raise RuntimeError(
                    f"向量索引 {ENTITY_VECTOR_INDEX} 已存在且维度为 {configured}，"
                    f"与当前 embedding_dim={self._dim} 不符"
                )
        # 相似度省略即默认 cosine（见 chunk_index.py 同款注释）
        await self._driver.execute_query(
            cast(
                "LiteralString",
                f"CREATE VECTOR INDEX {ENTITY_VECTOR_INDEX} IF NOT EXISTS "
                "FOR (e:Entity) ON (e.embedding) "
                f"OPTIONS {{indexConfig: {{`vector.dimensions`: {self._dim}}}}}",
            ),
            database_=self._database,
        )
        logger.info("Neo4j graph 索引就绪: entity(name_norm/全文/向量 dim=%d)", self._dim)

    # ---- 写入 / 删除 ----

    async def upsert_document_graph(
        self,
        *,
        document_id: str,
        entities: Sequence[GraphEntity],
        triples: Sequence[GraphTriple],
    ) -> int:
        """整篇替换该文档的图贡献：剔本篇证据 → 删掏空的边 → 清遗留支撑 →
        MERGE 实体 → 回写边与证据 → 扫孤儿（独立一发）。

        规范边 MERGE 命中他篇共用的旧边时只追加本篇证据，不再抢归属——
        旧 r.doc_id 最后写入者占用的方案随 SUPPORTS 一起退役。

        复活守卫（2026-09-15 验尸所得）：开写前先确认本篇还有 chunk。删除
        超车慢抽取时（chunk 已删、scrub 已跑，LLM 结果才回来），原料已失，
        整篇放弃写入——否则 MERGE 会凭空造出"证据指向幽灵坐标"的僵尸子图。
        """

        guard = await self._driver.execute_query(
            "MATCH (c:Chunk {doc_id: $doc}) RETURN count(c) AS n",
            doc=document_id,
            database_=self._database,
        )
        if not guard.records or int(guard.records[0]["n"]) == 0:
            logger.warning("放弃图写入：文档 %s 无检索 chunk（已删除或正在重建）", document_id)
            return 0

        await self._driver.execute_query(
            # 本篇证据清账：非本篇条目原样保留（这就是多出处共存的地方）
            "MATCH ()-[r:REL]->() "
            "SET r.evidence = [x IN coalesce(r.evidence, []) WHERE NOT x STARTS WITH $prefix] "
            "WITH count(*) AS scrubbed "
            "MATCH ()-[r:REL]->() WHERE COALESCE(size(r.evidence), 0) = 0 DELETE r "
            "WITH count(*) AS dropped "
            # 过渡期子句：SUPPORTS 退役后清掉本篇旧边，全库 rerun 完即空转
            "MATCH (c:Chunk {doc_id: $doc})-[s:SUPPORTS]->() DELETE s "
            "WITH count(*) AS cleared_supports "
            "UNWIND $entities AS ent "
            "MERGE (e:Entity {name_norm: ent.name_norm}) "
            "  SET e.name = ent.name, e.type = ent.type, e.description = ent.description, "
            "      e.embedding = ent.embedding, "
            # aliases 只增不减的并集（REDUCE 去重）：同一实体先后被抽成
            # apple / Apples 时，第二次把第一个表面形并进别名，链接面自愈
            "      e.aliases = REDUCE(acc = [], v IN coalesce(e.aliases, []) "
            "        + ent.aliases + [toLower(ent.name)] "
            "        | CASE WHEN v IN acc THEN acc ELSE acc + v END) "
            "WITH count(*) AS upserted "
            "UNWIND $triples AS t "
            "MATCH (a:Entity {name_norm: t.src_norm}), (b:Entity {name_norm: t.dst_norm}) "
            "MERGE (a)-[r:REL {type: t.relation}]->(b) "
            # 同篇多块挺同一事实时批内也会撞边：REDUCE 去重追加
            "SET r.evidence = REDUCE(acc = coalesce(r.evidence, []), v IN [t.evidence] "
            "  | CASE WHEN v IN acc THEN acc ELSE acc + v END) "
            "RETURN count(*) AS written_triples",
            doc=document_id,
            prefix=f"{document_id}:",
            entities=[asdict(e) for e in entities],
            triples=[
                {**asdict(t), "evidence": f"{document_id}:{t.chunk_index}"} for t in triples
            ],
            database_=self._database,
        )
        await self._sweep_orphan_entities()
        return len(entities)

    async def _sweep_orphan_entities(self) -> None:
        """孤儿清扫独立成查询：若把它缀在主查询末尾，`MATCH...DELETE` 匹配 0 个
        孤儿时会把行流吞光，后面的 RETURN 返回空 records（活体踩过的坑）。"""

        await self._driver.execute_query(
            "MATCH (e:Entity) WHERE NOT (e)--() DELETE e",
            database_=self._database,
        )

    async def delete_document_graph(self, document_id: str) -> None:
        """从所有 REL 边的证据列表里减掉本篇（LightRAG subtract_source_ids 同款），
        掏空的边删除；遗留 SUPPORTS 一并清掉（幂等，重投无害）。"""

        await self._driver.execute_query(
            "MATCH ()-[r:REL]->() "
            "SET r.evidence = [x IN coalesce(r.evidence, []) WHERE NOT x STARTS WITH $prefix] "
            "WITH count(*) AS scrubbed "
            "MATCH ()-[r:REL]->() WHERE COALESCE(size(r.evidence), 0) = 0 DELETE r "
            "WITH count(*) AS dropped "
            "MATCH (c:Chunk {doc_id: $doc})-[s:SUPPORTS]->() DELETE s",
            doc=document_id,
            prefix=f"{document_id}:",
            database_=self._database,
        )
        await self._sweep_orphan_entities()

    # ---- 检索原语 ----

    async def link_by_names(self, names: list[str], *, limit: int) -> list[str]:
        """别名精确匹配query改写得到的entities的名字"""

        cleaned = [n.strip().casefold() for n in names if n and n.strip()]
        if not cleaned:
            return []
        result = await self._driver.execute_query(
            "UNWIND $names AS nm "
            "MATCH (e:Entity) "
            "WITH e, nm WHERE e.name_norm = nm "
            "  OR any(a IN coalesce(e.aliases, []) WHERE a = nm) "
            "RETURN collect(DISTINCT e.name_norm)[0..$limit] AS norms",
            names=cleaned,
            limit=limit,
            database_=self._database,
        )
        if not result.records:
            return []
        return [str(x) for x in (result.records[0]["norms"] or [])]

    async def link_by_text(self, query_text: str, *, limit: int) -> list[str]:
        """BM25 找 entity"""

        lucene = fulltext_query(query_text)
        if not lucene:
            return []
        result = await self._driver.execute_query(
            f"CALL db.index.fulltext.queryNodes('{ENTITY_TEXT_INDEX}', $query) "
            "YIELD node, score WHERE score > 0 "
            "RETURN DISTINCT node.name_norm AS norm ORDER BY norm LIMIT $limit",
            query=lucene,
            limit=limit,
            database_=self._database,
        )
        return [str(r["norm"]) for r in result.records if r["norm"] is not None]

    async def link_by_vector(
        self, vector: list[float], *, limit: int, min_score: float
    ) -> list[str]:
        """dense search 找 entity"""
        if min_score <= 0 or not vector:
            return []  # 阈值 <=0 视为关闭向量链接（省一次 ANN；不是"全放过"）
        result = await self._driver.execute_query(
            f"CALL db.index.vector.queryNodes('{ENTITY_VECTOR_INDEX}', $limit, $vector) "
            "YIELD node, score WHERE score >= $min_score "
            "RETURN node.name_norm AS norm, score ORDER BY score DESC",
            limit=limit,
            vector=vector,
            min_score=min_score,
            database_=self._database,
        )
        return [str(r["norm"]) for r in result.records if r["norm"] is not None]

    async def expand_from(self, seeds: list[str], *, hops: int, limit: int) -> list[dict]:
        """graph search 寻找匹配的seed的最近的作为relationship的evidence的chunks 和 排名用于RRF"""

        if not seeds:
            return []  # 没有seed 直接返回
        hops = max(1, min(int(hops), 3))  # 最多3跳
        result = await self._driver.execute_query(
            cast(
                "LiteralString",
                "UNWIND $seeds AS seed "
                "MATCH (e:Entity {name_norm: seed}) "
                f"MATCH path = (e)-[:REL*1..{hops}]-(n:Entity) "  # 找hops跳能达到的entity
                "WITH length(path) AS hops, "
                "     reduce(ev = [], p IN relationships(path) "
                "       | ev + coalesce(p.evidence, [])) AS evidence "# 找到到邻居的所有path的evidence
                # length(path) evidences  多对多
                "UNWIND evidence AS coord "
                "WITH coord, min(hops) AS hops "
                # evidence min(hops) 按 seed 到 n 的距离排序 
                "MATCH (c:Chunk {doc_id: split(coord, ':')[0], "
                "chunk_index: toInteger(split(coord, ':')[1])}) "
                "RETURN hops, c.doc_id AS doc, c.chunk_index AS idx, c.text AS text, "
                "       c.document_name AS name, c.chunk_count AS cnt "
                "ORDER BY hops LIMIT $limit",
            ),
            seeds=seeds,
            limit=limit,
            database_=self._database,
        )
        hits: list[dict] = []
        for rank, record in enumerate(result.records):
            hits.append(
                {
                    "point_id": f"{record['doc']}:{record['idx']}",
                    "document_id": str(record["doc"]),
                    "document_name": record["name"],
                    "chunk_index": int(record["idx"]),
                    "chunk_count": int(record["cnt"]) if record["cnt"] is not None else None,
                    "text": record["text"],
                    "score": float(len(result.records) - rank),# 通道内名次分用于后续RRF
                }
            )
        return hits

    async def neighborhood(self, seeds: list[str], *, hops: int, limit: int) -> dict:
        """输入seed 寻找seed hops跳内能达到的顶点 和 neighbor之间的边"""

        if not seeds:
            return {"nodes": [], "edges": []}
        hops = max(1, min(int(hops), 3))  # 最多3跳
        nodes_result = await self._driver.execute_query(
            cast(
                "LiteralString",
                "UNWIND $seeds AS seed "
                "MATCH (s:Entity {name_norm: seed}) "
                f"MATCH path = (s)-[:REL*0..{hops}]-(n:Entity) "# 包括自己
                "WITH n, length(path) AS d, "
                "     reduce(ev = [], p IN relationships(path) "
                "       | ev + coalesce(p.evidence, [])) AS evidence "
                "ORDER BY d ASC, size(evidence) DESC " # 按 路径长度和证据数量 排序
                # n length(path) evidence 
                "WITH n, head(collect({hops: d, evidence_cnt: size(evidence)})) AS best "
                "ORDER BY best.hops ASC, best.evidence_cnt DESC " # 每个节点 仅取涉及到的path和对应的evidence中
                # path最短的 evidence最多的 
                "LIMIT $limit "
                "RETURN n.name_norm AS norm, n.name AS name, n.type AS type, "
                "       best.hops AS hops, best.evidence_cnt AS path_evidence",
            ),
            seeds=seeds,
            limit=limit,
            database_=self._database,
        )
        nodes = [
            {
                "name_norm": str(r["norm"]),
                "name": r["name"],
                "type": r["type"],
                "hops": int(r["hops"]),
                "path_evidence": int(r["path_evidence"]),
            }
            for r in nodes_result.records
        ]
        if not nodes:
            return {"nodes": [], "edges": []}
        norms = [n["name_norm"] for n in nodes] #
        edges_result = await self._driver.execute_query(
            "UNWIND $norms AS nm "
            "MATCH (e:Entity {name_norm: nm}) "
            "MATCH (e)-[r:REL]->(b:Entity) "
            "WHERE b.name_norm IN $norms " # 收集neighbor中的相互连接的edge
            "RETURN e.name_norm AS src, b.name_norm AS dst, r.type AS type, "
            "       coalesce(r.evidence, []) AS evidence "
            "ORDER BY src, dst, type",
            norms=norms,
            database_=self._database,
        )
        edges = [
            {
                "src": str(r["src"]),
                "dst": str(r["dst"]),
                "type": str(r["type"]),
                "evidence": [str(x) for x in (r["evidence"] or [])],
            }
            for r in edges_result.records
        ]
        return {"nodes": nodes, "edges": edges}

    async def search_entities(self, query: str, *, limit: int = 8) -> list[dict]:
        """按实体名称精准/前缀/包含匹配候选实体卡片。"""

        q = query.strip()
        if not q:
            result = await self._driver.execute_query(
                "MATCH (e:Entity) "
                "OPTIONAL MATCH (e)-[r:REL]-() "
                "WITH e, count(r) AS degree, "
                "     reduce(acc = 0, x IN collect(r) "
                "       | acc + size(coalesce(x.evidence, []))) AS ev_count "
                "RETURN e.name_norm AS norm, e.name AS name, e.type AS type, "
                "       e.description AS description, degree, ev_count AS evidence_count "
                "ORDER BY degree DESC, ev_count DESC " # 默认展示度最大 总和evidence最多的entity
                "LIMIT $limit",
                limit=limit,
                database_=self._database,
            )
        else:
            result = await self._driver.execute_query(
                "MATCH (e:Entity) "
                "WHERE e.name CONTAINS $q OR e.name_norm CONTAINS $q "
                "   OR any(a IN coalesce(e.aliases, []) WHERE a CONTAINS $q) "
                "OPTIONAL MATCH (e)-[r:REL]-() "
                "WITH e, count(r) AS degree, "
                "     reduce(acc = 0, x IN collect(r) "
                "       | acc + size(coalesce(x.evidence, []))) AS ev_count, "
                "     CASE "
                "       WHEN e.name_norm = $q OR e.name = $q THEN 0 " # 精确匹配
                "       WHEN e.name STARTS WITH $q OR e.name_norm STARTS WITH $q THEN 1 " # 前缀匹配
                "       WHEN any(a IN coalesce(e.aliases, []) WHERE a STARTS WITH $q) THEN 2 " # 别名前缀匹配
                "       ELSE 3 " # 前缀不够了再找匹配
                "     END AS priority "
                "RETURN e.name_norm AS norm, e.name AS name, e.type AS type, "
                "       e.description AS description, degree, ev_count AS evidence_count "
                "ORDER BY priority ASC, degree DESC, ev_count DESC "
                "LIMIT $limit",
                q=q,
                limit=limit,
                database_=self._database,
            )
        return [
            {
                "name_norm": str(r["norm"]),
                "name": r["name"],
                "type": r["type"],
                "description": r["description"],
                "degree": int(r["degree"]),
                "evidence_count": int(r["evidence_count"]),
            }
            for r in result.records
        ]


__all__ = ["Neo4jGraphRepository"]
