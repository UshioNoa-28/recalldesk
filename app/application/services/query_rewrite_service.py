"""查询改写服务：把原始查询改写成对混合检索更友好的形式（多路版）。

一次 LLM 结构化调用输出：
- queries：N 个语义变体（每个变体 dense embedding 一路）
- keywords：一组高信号关键词（sparse/BM25 单路共用）

走 OpenAI 协议的结构化输出（LlmClient.generate_structured），
输出不符号 schema 时由 LLM 客户端直接抛错——刻意不做静默回退，
改写失败应当显式暴露，而不是悄悄退化成不改写。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from app.ports.llm_client import LlmClient

PROMPT = """You are a search query rewriter for hybrid retrieval (dense + BM25).

Given the raw query, produce:
- queries: {n_variants} semantically DIVERSE rewrites of the query
  (different phrasings / related aspects / broader-or-narrower formulations;
  same language as the input; preserve original intent, no invented facts)
- keywords: 3-8 high-signal keywords for lexical/BM25 matching
  (entities and terms, no filler words)

Output ONLY JSON: {{"queries": ["...", "..."], "keywords": ["...", "..."]}}

Raw query: {query}"""


class QueryRewriteOutput(BaseModel):
    """LLM 结构化输出的 schema（OpenAI json_schema / tool calling 用）。"""

    queries: list[str] = Field(min_length=1, description="语义多样的检索改写变体")
    keywords: list[str] = Field(default_factory=list, description="BM25 高信号关键词")


@dataclass
class QueryRewrite:
    queries: list[str]
    keywords: list[str] = field(default_factory=list)

    @property
    def sparse_text(self) -> str:
        """稀疏通道（BM25）实际使用的查询文本。"""

        return " ".join(self.keywords) if self.keywords else self.queries[0]


class QueryRewriteService:
    """查询改写编排。

    LLM 调用失败照常抛错 这里只兜 degenerate 输出：
    变体/关键词全是空白时退回原始查询，不让检索挂掉。
    """

    def __init__(self, *, llm_client: LlmClient) -> None:
        self._llm_client = llm_client

    async def rewrite(self, query: str, *, n_variants: int = 3) -> QueryRewrite:
        out = await self._llm_client.generate_structured(
            PROMPT.format(query=query, n_variants=n_variants), QueryRewriteOutput
        )
        # schema 的 min_length=1 只管列表长度，挡不住空白字符串；
        # 全空白时退回原始查询——queries[0] 是 sparse_text 的兜底，
        # 列表一旦为空就是 IndexError，整个 /search 跟着 500
        queries = [q.strip() for q in out.queries if q.strip()] or [query]
        keywords = [k.strip() for k in out.keywords if k.strip()]
        return QueryRewrite(queries=queries, keywords=keywords)


__all__ = ["QueryRewrite", "QueryRewriteOutput", "QueryRewriteService"]
