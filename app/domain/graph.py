"""知识图谱域模型：抽取任务（第四条 outbox 链路）+ 图写入的类型化载荷。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum


class GraphTaskStatus(StrEnum):
    """与文档/Eval 出箱链路同款状态机。"""

    PENDING = "pending"
    QUEUE = "queue"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class GraphTask:
    """一篇文档的图谱抽取任务（operation 恒为 extract，字段留口给后续 cleanup）。"""

    id: str
    document_id: str
    status: GraphTaskStatus
    attempts: int
    last_error: str | None
    created_at: datetime
    queued_at: datetime | None


# ---- 图写入的载荷类型：app 层与 GraphRepository 端口的契约 ----
# 之前是三个裸 dict 飘过边界（键名拼错要到 Neo4j 运行期才炸），
# 现在字段名即 Cypher 参数名的来源（asdict 直转），类型系统替你把关。


@dataclass(frozen=True)
class GraphEntity:
    name_norm: str  # 归一键（casefold+空白折叠）；MERGE 的锚
    name: str  # 展示用表面形（全文索引吃它，不吃 name_norm）
    type: str = "其他"
    description: str = ""
    aliases: tuple[str, ...] = ()
    embedding: list[float] | None = None  # 归一化后的名称描述句向量


@dataclass(frozen=True)
class GraphTriple:
    src_norm: str
    dst_norm: str
    relation: str  # REL.type 属性；同名 REL 标签防类型爆炸
    chunk_index: int  # 这条关系抽自哪块 → store 编成 "doc_id:chunk_index" 进 REL.evidence


@dataclass
class GraphContribution:
    """一篇文档的完整图贡献（抽取产物，字段与 GraphRepository.upsert_document_graph 对齐）。"""

    entities: list[GraphEntity] = field(default_factory=list)
    triples: list[GraphTriple] = field(default_factory=list)

    def with_embeddings(self, vectors: list[list[float]]) -> GraphContribution:
        """把批量 embedding 结果装回实体（frozen，replace 出新的）。"""

        if len(vectors) != len(self.entities):
            raise ValueError("embedding 数量与实体数量不一致")
        return GraphContribution(
            entities=[
                replace(entity, embedding=vector)
                for entity, vector in zip(self.entities, vectors, strict=True)
            ],
            triples=list(self.triples),
        )


__all__ = [
    "GraphContribution",
    "GraphEntity",
    "GraphTask",
    "GraphTaskStatus",
    "GraphTriple",
]
