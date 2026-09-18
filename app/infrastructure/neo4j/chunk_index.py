"""ChunkIndex 的 Neo4j 实现：一个 Chunk 节点 = 一行可检索分块。

节点形态（本阶段图还没长出来，只有 :Chunk 一种标签）：

    (:Chunk {doc_id, chunk_index, text, document_name, chunk_count})
        - text 属性喂 db.index.fulltext（Lucene BM25，cjk 分词）
        - 待填的 embedding 属性喂 db.index.vector（HNSW cosine）

纪律与 Qdrant 时代一致：分块文本只活在这里（PG 不落副本），
但这里的一切都是**磁盘原始文件 + 重索引**可随时重建的派生物——
库丢了不心疼，reindex 一键回魂。

一致性边界（与 outbox 语义配套）：Neo4j 写不进 PG 事务，所以
upsert 放在 consumer 的 PG 事务之前、且整篇替换幂等——最坏情况是
"索引已写但任务未落终态"，重投再来一次同样的全量替换，无害。

驱动把查询文本钉成 LiteralString（防注入警铃）：字面量/模块常量拼的
Cypher 天然过关；必须插运行时值（维度、分析器名）的几处用
cast(LiteralString, ...) 统一放行——插值全是内部计算值，无外部输入。
"""

from __future__ import annotations

import logging
from typing import LiteralString, cast

from neo4j import AsyncDriver

from app.infrastructure.neo4j.lucene import fulltext_query as _fulltext_query
from app.ports.chunk_index import ChunkIndex

logger = logging.getLogger(__name__)

DENSE_INDEX = "chunk_embedding"
SPARSE_INDEX = "chunk_text"
CHUNK_KEY_CONSTRAINT = "chunk_doc_key"


def _hit(
    node_doc_id: str,
    node_name: str,
    chunk_index: int,
    chunk_count: int,
    text: str,
    score: float,
) -> dict:
    return {
        "point_id": f"{node_doc_id}:{chunk_index}",  # RRF 合并键：两路必须同口径
        "document_id": node_doc_id,
        "document_name": node_name,
        "chunk_index": int(chunk_index),
        "chunk_count": int(chunk_count) if chunk_count is not None else None,
        "text": text,
        "score": float(score),
    }


class Neo4jChunkIndex(ChunkIndex):
    """dense（HNSW 向量索引）+ sparse（Lucene 全文索引）两路的 Neo4j adapter。"""

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
        """幂等建索引，并校验已存在的向量索引维度（对齐旧 ensure_collection 的语义）。

        CREATE ... IF NOT EXISTS 对"已存在但维度不符"的索引是静默跳过的，
        换 embedding 模型时会得到一堆运行时迷惑错误——所以先 SHOW 再比维度，
        不对就直接抛，把问题钉死在启动那一刻。
        """

        await self._driver.execute_query(
            f"CREATE CONSTRAINT {CHUNK_KEY_CONSTRAINT} IF NOT EXISTS "
            "FOR (c:Chunk) REQUIRE (c.doc_id, c.chunk_index) IS UNIQUE",
            database_=self._database,
        )
        rows = await self._driver.execute_query(
            "SHOW VECTOR INDEXES YIELD name, options WHERE name = $name "
            "RETURN options.indexConfig AS cfg",
            name=DENSE_INDEX,
            database_=self._database,
        )
        for record in rows.records:
            cfg = record["cfg"] or {}
            configured = int(cfg.get("vector.dimensions", self._dim))
            if configured != self._dim:
                raise RuntimeError(
                    f"向量索引 {DENSE_INDEX} 已存在且维度为 {configured}，"
                    f"与当前 embedding_dim={self._dim} 不符："
                    "换模型需要删旧索引重建（或清空 Neo4j 后重启）"
                )
        await self._driver.execute_query(
            # 相似度默认就是 cosine；刻意不写 vector.similarity_function 这个键——
            # 它在 Neo4j 5 各小版本里在 `vector.similarity.function`(点) 与
            # `vector.similarity_function`(下划线) 之间改过名，省略即吃默认、免疫该漂移。
            cast(
                "LiteralString",
                f"CREATE VECTOR INDEX {DENSE_INDEX} IF NOT EXISTS "
                "FOR (c:Chunk) ON (c.embedding) "
                "OPTIONS {indexConfig: {`vector.dimensions`: " + str(self._dim) + "}}",
            ),
            database_=self._database,
        )
        await self._driver.execute_query(
            # Neo4j 5 的全文分析器键是 `fulltext.analyzer`（带 fulltext. 前缀），
            # 不是裸 `analyzer`——后者是 4.x 写法，5 会报 "not recognized as an index setting"。
            cast(
                "LiteralString",
                f"CREATE FULLTEXT INDEX {SPARSE_INDEX} IF NOT EXISTS "
                "FOR (c:Chunk) ON EACH [c.text] "
                f"OPTIONS {{indexConfig: {{`fulltext.analyzer`: '{self._analyzer}'}}}}",
            ),
            database_=self._database,
        )
        logger.info(
            "Neo4j chunk 索引就绪: vector(dim=%d, cosine) + fulltext(analyzer=%s)",
            self._dim,
            self._analyzer,
        )

    # ---- 写入 / 删除 ----

    async def upsert_chunks(
        self,
        *,
        document_id: str,
        document_name: str,
        chunks: list[str],
        vectors: list[list[float]],
    ) -> int:
        """整篇替换：先 DETACH DELETE 旧块，再 UNWIND 批量建（一次往返）。

        维度不符在这里兜底（ensure 之后模型配置理论上不会再变，防的是手滑）：
        错维度写进 HNSW 会让索引静默报废，比抛错坏一万倍。
        """

        if len(chunks) != len(vectors):
            raise ValueError(f"chunks 与 vectors 数量不一致: {len(chunks)} != {len(vectors)}")
        for i, vector in enumerate(vectors):
            if len(vector) != self._dim:
                raise ValueError(
                    f"vectors[{i}] 维度是 {len(vector)}，与 embedding_dim={self._dim} 不符"
                )

        rows = [
            {
                "idx": index,
                "text": chunk,
                "vec": vector,
                "name": document_name,
                "count": len(chunks),
            }
            for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
        ]
        await self._driver.execute_query(
            "MATCH (c:Chunk {doc_id: $doc_id}) DETACH DELETE c "
            "WITH count(*) AS cleared "
            "UNWIND $rows AS row "
            "CREATE (:Chunk {doc_id: $doc_id, chunk_index: row.idx, text: row.text,"
            " embedding: row.vec, document_name: row.name, chunk_count: row.count})",
            doc_id=document_id,
            rows=rows,
            database_=self._database,
        )
        return len(rows)

    async def delete_document(self, *, document_id: str) -> None:
        await self._driver.execute_query(
            "MATCH (c:Chunk {doc_id: $doc_id}) DETACH DELETE c",
            doc_id=document_id,
            database_=self._database,
        )
    async def search_by_dense(self, *, dense_vector: list[float], top_k: int) -> list[dict]:
        """dense search neo4j 实现 """
        rows = await self._driver.execute_query(
            f"CALL db.index.vector.queryNodes('{DENSE_INDEX}', $limit, $vector) "
            "YIELD node, score "
            "RETURN node.doc_id AS doc, node.document_name AS name,"
            " node.chunk_index AS idx, node.chunk_count AS cnt, node.text AS text, score "
            "ORDER BY score DESC",
            limit=top_k,
            vector=dense_vector,
            database_=self._database,
        )
        return [
            _hit(r["doc"], r["name"], r["idx"], r["cnt"], r["text"], r["score"])
            for r in rows.records
        ]

    async def search_by_sparse(self, *, query_text: str, top_k: int) -> list[dict]:
        """sparse search neo4j 实现"""
        lucene = _fulltext_query(query_text)
        if not lucene:
            return []  # 纯符号/空白查询：没词可查，空手回（不报错）
        rows = await self._driver.execute_query(
            f"CALL db.index.fulltext.queryNodes('{SPARSE_INDEX}', $query) "
            "YIELD node, score WHERE score > 0 "
            "RETURN node.doc_id AS doc, node.document_name AS name,"
            " node.chunk_index AS idx, node.chunk_count AS cnt, node.text AS text, score "
            "ORDER BY score DESC LIMIT $limit",
            query=lucene,
            limit=top_k,
            database_=self._database,
        )
        return [
            _hit(r["doc"], r["name"], r["idx"], r["cnt"], r["text"], r["score"])
            for r in rows.records
        ]

    async def get_document_chunks(self, *, document_id: str) -> list[dict]:
        rows = await self._driver.execute_query(
            "MATCH (c:Chunk {doc_id: $doc_id}) "
            "RETURN c.chunk_index AS idx, c.text AS text, c.document_name AS name, "
            "c.chunk_count AS cnt ORDER BY idx",
            doc_id=document_id,
            database_=self._database,
        )
        return [
            {
                "chunk_index": int(r["idx"]),
                "text": r["text"],
                "document_name": r["name"],
                "chunk_count": int(r["cnt"]) if r["cnt"] is not None else None,
            }
            for r in rows.records
        ]

    async def get_chunk(self, *, document_id: str, chunk_index: int) -> dict | None:
        rows = await self._driver.execute_query(
            "MATCH (c:Chunk {doc_id: $doc_id, chunk_index: $idx}) "
            "RETURN c.text AS text, c.document_name AS name, c.chunk_count AS cnt",
            doc_id=document_id,
            idx=chunk_index,
            database_=self._database,
        )
        if not rows.records:
            return None
        r = rows.records[0]
        return {
            "document_id": document_id,
            "chunk_index": chunk_index,
            "text": r["text"],
            "document_name": r["name"],
            "chunk_count": int(r["cnt"]) if r["cnt"] is not None else None,
        }

    async def close(self) -> None:
        # 驱动生命周期归容器 teardown；这里只是端口的对称收尾，不重复关
        return None


__all__ = ["Neo4jChunkIndex"]
