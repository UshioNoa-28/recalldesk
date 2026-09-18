"""图谱抽取编排：每块一次结构化 LLM 调用 → 归并实体/关系，产出整篇贡献。

设计口径：
- 抽取单位是 chunk（一次调用出多个三元组），带并发闸防中转限流；
- 实体按 name_norm（strip+casefold）跨块归并；词形问题的第一道防线在提示词里
  （要求单数/原形/全称——LLM 是最便宜的归一化器），第二道在 store 的别名并集；
- 三元组端点必须在同一块的实体名里找得到——LLM 手滑引用了没声明的实体，
  这条三元组直接丢弃并告警（幻影边比漏边毒得多）；
- 实体 embedding：`name（type）：description` 一句过 embedding，供链接兜底。

失败策略：任何一块抽取异常 = 整篇任务失败回退避重投（幂等替换不怕重跑），
不在这里做部分成功——半篇图谱比没有更难排查。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pydantic import BaseModel, Field

from app.domain.graph import GraphContribution, GraphEntity, GraphTriple
from app.ports.model_clients.embedding_client import EmbeddingClient
from app.ports.model_clients.llm_client import LlmClient

logger = logging.getLogger(__name__)

PROMPT = """你是知识图谱抽取器。从下面的文本块中抽取实体与关系，
只抽文本明确陈述的内容，不做推理补全。

要求：
- entities：至多 {max_entities} 个核心实体；name 用文中最完整的正式名；
  英文实体一律给单数原形（apple 而非 apples，run 而非 running），
  中文实体不带"们/这种/等"后缀；别名放进 aliases；
  type 从 [人物, 组织, 地点, 产品, 概念, 物质, 疾病, 文档, 其他] 中选；
  description 一句话概括
- triples：至多 {max_triples} 条；src、dst 必须出现在上面 entities 的 name 里；
  relation 用 2-6 字动宾短语（如：富含、位于、属于、服用禁忌）
- 宁缺毋滥：拿不准的不抽

文档：《{document_name}》
切片 #{chunk_index}：
{text}"""


class GraphEntityOut(BaseModel):
    """LLM 输出：一个实体。"""

    name: str = Field(min_length=1)
    type: str = "其他"
    description: str = ""
    aliases: list[str] = Field(default_factory=list)


class GraphTripleOut(BaseModel):
    """LLM 输出：一条三元组（端点用实体 name 原文）。"""

    src: str
    dst: str
    relation: str


class GraphChunkExtraction(BaseModel):
    """单块抽取的结构化输出 schema（generate_structured 用）。"""

    entities: list[GraphEntityOut] = Field(default_factory=list)
    triples: list[GraphTripleOut] = Field(default_factory=list)


def normalize_name(name: str) -> str:
    """实体归一键：空白折叠 + casefold；展示仍用原名。"""

    return " ".join(name.split()).casefold()


class GraphExtractionService:
    def __init__(
        self,
        *,
        llm_client: LlmClient,
        embedding_client: EmbeddingClient,
        concurrency: int = 2,
        max_entities: int = 8,
        max_triples: int = 8,
    ) -> None:
        self._llm = llm_client
        self._embedding = embedding_client
        self._concurrency = max(1, concurrency) # 防上游爆炸
        self._max_entities = max_entities
        self._max_triples = max_triples

    async def build(self, document_name: str, chunks: list[dict]) -> GraphContribution:
        """ llm 抽取 得到 entity 和 triple 返回 entity 及其对应的 dense embedding描述 以及 triple"""

        semaphore = asyncio.Semaphore(self._concurrency)

        async def extract(chunk: dict) -> tuple[int, GraphChunkExtraction]:
            async with semaphore:
                prompt = PROMPT.format(
                    max_entities=self._max_entities,
                    max_triples=self._max_triples,
                    document_name=document_name,
                    chunk_index=chunk["chunk_index"],
                    text=str(chunk.get("text") or "")[:2000],
                )
                out = await self._llm.generate_structured(prompt, GraphChunkExtraction)
                return int(chunk["chunk_index"]), out

        # 累积槽（可变），最后一步才冻结成 dataclass
        slots: dict[str, dict[str, Any]] = {}
        triples: list[GraphTriple] = []

        for chunk_index, out in await asyncio.gather(*(extract(c) for c in chunks)):
            by_surface: dict[str, str] = {}# 统计所有的entity的name和alias 用于判断REL的合法性
            for entity in out.entities:
                name = entity.name.strip()
                if not name:
                    continue
                norm = normalize_name(name)
                slot = slots.setdefault(
                    norm,
                    {
                        "name": name,
                        "type": entity.type.strip() or "其他",
                        "description": entity.description.strip(),
                        "aliases": {a.strip().casefold() for a in entity.aliases if a.strip()},
                    },
                )
                slot["aliases"] |= {a.strip().casefold() for a in entity.aliases if a.strip()}
                slot["aliases"].discard(norm) # 原名不属于别名
                by_surface[norm] = norm
                for alias in entity.aliases:
                    a = normalize_name(alias or "")
                    if a and a != norm:
                        by_surface.setdefault(a, norm)

            for triple in out.triples:
                src = by_surface.get(normalize_name(triple.src))
                dst = by_surface.get(normalize_name(triple.dst))
                relation = triple.relation.strip()
                if not src or not dst or src == dst or not relation:
                    logger.warning(
                        "丢弃越界三元组: %s -[%s]-> %s (chunk #%s)",
                        triple.src,
                        relation,
                        triple.dst,
                        chunk_index,
                    )
                    continue
                triples.append(
                    GraphTriple(
                        src_norm=src,
                        dst_norm=dst,
                        relation=relation,
                        chunk_index=chunk_index,
                    )
                )

        entities = [
            GraphEntity(
                name_norm=norm,
                name=slot["name"],
                type=slot["type"],
                description=slot["description"],
                aliases=tuple(sorted(slot["aliases"])),
            )
            for norm, slot in slots.items()
        ]
        contribution = GraphContribution(entities=entities, triples=triples)
        if entities:
            contribution = contribution.with_embeddings(await self._embed(entities))
        return contribution

    async def _embed(self, entities: list[GraphEntity]) -> list[list[float]]:
        """"""

        texts = [
            f"{e.name}({e.type}):{e.description or 'no description'}" for e in entities
        ]
        return await self._embedding.embed(texts)


__all__ = [
    "GraphChunkExtraction",
    "GraphEntityOut",
    "GraphExtractionService",
    "GraphTripleOut",
    "normalize_name",
]
