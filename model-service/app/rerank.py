from __future__ import annotations

import asyncio
import logging
import math
from contextlib import nullcontext

import httpx

from app.config import Settings, settings
from app.errors import UpstreamError

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Judge whether the Document meets the requirements based on the Query "
    'and the Instruct provided. Note that the answer can only be "yes" or "no".'
)

INSTRUCT = "Given a web search query, retrieve relevant passages that answer the query"

# 两个 %s 依次是 query、document。
# 结尾是 Qwen3 chat template 在 enable_thinking=false 时的固定前缀：先吐一个空的
# <think></think> 块，再让首 token 落在 yes/no 上（带 em dash 会把它推进思考态）。
PROMPT_TEMPLATE = (
    "<|im_start|>system\n"
    + SYSTEM_PROMPT
    + "<|im_end|>\n"
    + "<|im_start|>user\n"
    + f"<Instruct>: {INSTRUCT}\n\n<Query>: %s\n\n<Document>: %s<|im_end|>\n"
    + "<|im_start|>assistant\n<think>\n\n</think>\n\n"
)

MAX_ATTEMPTS = 3


def _brief(body: str) -> str:
    text = (body or "").strip()
    return text if len(text) <= 300 else text[:300]


def yes_probability(root: dict) -> float:
    """从首 token 的 top_logprobs 里取 yes/no，返回归一化 P(yes)。

    缺 token 时按 0 分处理并留痕，不让单个坏响应打断整批重排。
    """
    logprobs = root.get("logprobs")
    if not isinstance(logprobs, list) or not logprobs:
        logger.warning("Ollama 未返回 logprobs，该候选按 0 分处理")
        return 0.0

    entries = logprobs[0].get("top_logprobs") or []
    yes: float | None = None
    no: float | None = None
    for entry in entries:
        token = str(entry.get("token", "")).strip().lower()
        logprob = float(entry.get("logprob") or 0.0)
        # 只认第一个：同一个 token 以不同大小写出现两次时，取先见的那个
        if yes is None and token == "yes":
            yes = logprob
        elif no is None and token == "no":
            no = logprob

    if yes is None and no is None:
        logger.warning("首 token 分布里没有 yes/no，该候选按 0 分处理")
        return 0.0

    p_yes = math.exp(yes) if yes is not None else 0.0
    p_no = math.exp(no) if no is not None else 0.0
    return p_yes / (p_yes + p_no) if p_yes + p_no > 0 else 0.0


def _payload(settings: Settings, prompt: str) -> dict:
    return {
        "model": settings.rerank_model,
        "prompt": prompt,
        "stream": False,
        "raw": True,
        "logprobs": True,
        "top_logprobs": settings.rerank_top_logprobs,
        "keep_alive": settings.rerank_keep_alive,
        "options": {
            "num_predict": 1,
            "temperature": 0,
            "num_ctx": settings.rerank_num_ctx,
        },
    }


async def _post(
    client: httpx.AsyncClient,
    settings: Settings,
    payload: dict,
    slots: asyncio.Semaphore | None,
) -> dict:
    # 信号量由 rerank_scores 按请求创建：模块级信号量会绑定首个使用它的事件循环
    async with slots if slots is not None else nullcontext():
        try:
            response = await client.post(
                f"{settings.ollama_root}/api/generate",
                json=payload,
                timeout=settings.rerank_timeout_seconds,
            )
        except httpx.RequestError as exc:
            raise UpstreamError(f"rerank 请求失败: {exc}", status_code=-1) from exc

    if response.status_code >= 400:
        raise UpstreamError(
            f"rerank HTTP {response.status_code}: {_brief(response.text)}",
            status_code=response.status_code,
        )
    try:
        return response.json()
    except ValueError as exc:
        raise UpstreamError("rerank 响应不是 JSON", status_code=-1) from exc


async def score_one(
    client: httpx.AsyncClient,
    settings: Settings,
    query: str,
    document: str,
    slots: asyncio.Semaphore | None = None,
) -> float:
    """一对 (query, document) -> P(yes)/(P(yes)+P(no))。"""
    prompt = PROMPT_TEMPLATE % (
        query.strip(),
        document[: settings.rerank_candidate_chars].strip(),
    )
    payload = _payload(settings, prompt)

    last_error: UpstreamError | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return yes_probability(await _post(client, settings, payload, slots))
        except UpstreamError as exc:
            if exc.status_code < 500:
                raise
            last_error = exc
            # 内存吃紧时 Ollama 会把模型换出，冷加载窗口内的请求回 5xx；重试等它换回来
            logger.warning("rerank 候选打分第 %s 次失败: %s", attempt, exc)
            await asyncio.sleep(5 * attempt)

    # 兜底 0 分——一个候选不该炸掉整次检索
    logger.warning(
        "rerank 候选三次均失败，按 0 分处理: %s",
        last_error if last_error is not None else "",
    )
    return 0.0


async def rerank_scores(
    client: httpx.AsyncClient,
    settings: Settings,
    query: str,
    documents: list[str],
) -> list[float]:
    if not documents:
        return []
    slots = asyncio.Semaphore(max(1, settings.rerank_concurrency))
    scores = list(
        await asyncio.gather(
            *(
                score_one(client, settings, query, document, slots)
                for document in documents
            )
        )
    )
    if scores and all(score == 0.0 for score in scores):
        # 典型原因是 RERANK_MODEL 不是可用的生成式重排模型（首 token 不给 yes/no）；
        # 检索不因此失败，但要让人看得见"这次重排实际上没起作用"
        logger.warning(
            "全部 %s 个候选重排分都是 0：检查 RERANK_MODEL=%s 是否能输出 yes/no",
            len(scores),
            settings.rerank_model,
        )
    return scores
