from __future__ import annotations

from pydantic import BaseModel, Field


class EmbedRequest(BaseModel):
    texts: list[str] = Field(default_factory=list)


class EmbedResponse(BaseModel):
    vectors: list[list[float]]
    dim: int


class RerankRequest(BaseModel):
    query: str
    documents: list[str] = Field(default_factory=list)


class RerankResponse(BaseModel):
    scores: list[float]


class RewriteRequest(BaseModel):
    query: str
    n_variants: int | None = None


class RewriteResponse(BaseModel):
    queries: list[str]
    keywords: list[str]
