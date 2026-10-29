from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.contracts import (
    EmbedRequest,
    EmbedResponse,
    RerankRequest,
    RerankResponse,
    RewriteRequest,
    RewriteResponse,
)
from app.embeddings import embed_texts
from app.errors import NotConfiguredError, UpstreamError
from app.llm import build_chat_models
from app.rerank import rerank_scores
from app.rewrite import rewrite_query

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient()
    app.state.chat, app.state.retry_chat = build_chat_models(settings)
    yield
    await app.state.http.aclose()


app = FastAPI(title="RecallDesk model gateway", lifespan=lifespan)


@app.exception_handler(UpstreamError)
async def upstream_error(_: Request, exc: UpstreamError) -> JSONResponse:
    status = exc.status_code if 400 <= exc.status_code <= 599 else 502
    return JSONResponse(status_code=status, content={"detail": str(exc)})


@app.exception_handler(NotConfiguredError)
async def not_configured_error(_: Request, exc: NotConfiguredError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/embed", response_model=EmbedResponse)
async def embed(request: Request, body: EmbedRequest) -> EmbedResponse:
    vectors = await embed_texts(request.app.state.http, settings, body.texts)
    return EmbedResponse(vectors=vectors, dim=settings.embedding_dim)


@app.post("/rerank", response_model=RerankResponse)
async def rerank(request: Request, body: RerankRequest) -> RerankResponse:
    if not settings.rerank_enabled:
        raise NotConfiguredError("未配置 RERANK_MODEL，重排不可用")
    scores = await rerank_scores(
        request.app.state.http, settings, body.query, body.documents
    )
    return RerankResponse(scores=scores)


@app.post("/rewrite", response_model=RewriteResponse)
async def rewrite(request: Request, body: RewriteRequest) -> RewriteResponse:
    chat = request.app.state.chat
    retry_chat = request.app.state.retry_chat
    if chat is None or retry_chat is None:
        raise NotConfiguredError("未配置 LLM_BASE_URL / LLM_MODEL，查询改写不可用")
    n_variants = body.n_variants or settings.rewrite_n_variants
    n_variants = max(1, min(n_variants, 10))
    return await rewrite_query(chat, retry_chat, body.query, n_variants)
