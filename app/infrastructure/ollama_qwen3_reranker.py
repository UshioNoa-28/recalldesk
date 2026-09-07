"""Ollama Qwen3-Reranker 适配器：生成式重排器走 /api/generate + logprobs。

Ollama 官方没有 rerank 端点，cross-encoder（成对打分类）模型在 Ollama 上
无法使用。Qwen3-Reranker 是生成式路线：按官方模型卡的 judge prompt
（system 判 yes/no + user 放 Instruct/Query/Document）构造完整 chat 模板，
让模型对「这段文档能否回答这个查询」输出 yes 或 no，再从首 token 的
logprobs 里取 P(yes)/(P(yes)+P(no)) 作为相关性分数。

要点：
- raw=true：prompt 已是完整 chat 模板，不能再让 Ollama 二次包裹；
- num_predict=1：只要首 token；分数取自首 token 分布里的 yes/no 两个
  token 的相对概率，与实际生成了什么无关（thinking 模型首 token 可能是
  @think 也无所谓）；
- 每对独立打分（pointwise），受限并发：并发数按内存预算来（见 __init__），
  延迟 ≈ 单对延迟 × ceil(候选数 / 并发数)。

延迟参考（Ryzen 7 8845H，Qwen3-Reranker-4B Q4_K_M，num_ctx=4096，并发 2）：
单对 1~2s，20 候选约 10~20s。
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any

import httpx

from app.ports.reranker import Reranker

logger = logging.getLogger(__name__)

# 官方模型卡的 judge prompt（Qwen3-Reranker 系列）
_SYSTEM_PROMPT = (
    "Judge whether the Document meets the requirements based on the Query "
    'and the Instruct provided. Note that the answer can only be "yes" or "no".'
)
_INSTRUCT = "Given a web search query, retrieve relevant passages that answer the query"

_PROMPT_TEMPLATE = (
    f"<|im_start|>system\n{_SYSTEM_PROMPT}<|im_end|>\n"
    "<|im_start|>user\n"
    f"<Instruct>: {_INSTRUCT}\n\n<Query>: {{query}}\n\n<Document>: {{document}}<|im_end|>\n"
    "<|im_start|>assistant\n\u2014\n\n"
)


class OllamaQwen3Reranker(Reranker):
    """对每个 (query, candidate) 对独立调 Ollama 打分，按 P(yes) 归一化排序。"""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        candidate_chars: int = 500,
        timeout: float = 60.0,
        num_ctx: int = 4096,
        concurrency: int = 2,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._candidate_chars = candidate_chars
        self._num_ctx = num_ctx
        # Ollama 的 llama-server 为每个并发请求分配独立 KV cache：并发 8 × 4096
        # ctx 在 13GB 内存的机器上会被 OOM killer 干掉。2 是实测安全值，
        # 内存充裕的机器可以调大
        self._semaphore = asyncio.Semaphore(concurrency)
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def rerank(
        self, *, query: str, candidates: list[dict], top_k: int
    ) -> list[dict]:
        if not candidates:
            return []

        # 每对独立打分，受限并发进 Ollama（并发过高会 OOM，见 __init__）
        scores = await asyncio.gather(
            *(
                self._score_one(query, c.get("text") or "")
                for c in candidates
            )
        )

        scored = sorted(
            zip(candidates, scores, strict=True),
            key=lambda pair: pair[1],
            reverse=True,
        )

        reranked: list[dict] = []
        for item, score in scored[:top_k]:
            out = dict(item)
            # 分数只用于排序：P(yes) 量纲与 RRF 分不同，不跨体系比较
            out["score"] = round(score, 4)
            reranked.append(out)
        return reranked

    async def _score_one(self, query: str, document: str) -> float:
        """一对 (query, document) -> P(yes)/(P(yes)+P(no))。"""

        prompt = _PROMPT_TEMPLATE.format(
            query=query.strip(), document=document[: self._candidate_chars].strip()
        )
        payload: dict[str, Any] = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "raw": True,
            "logprobs": True,
            "top_logprobs": 20,
            "options": {
                "num_predict": 1,
                "temperature": 0,
                "num_ctx": self._num_ctx,
            },
        }
        async with self._semaphore:
            response = await self._client.post(
                f"{self._base_url}/api/generate", json=payload
            )
        response.raise_for_status()
        return _yes_probability(response.json())

    async def close(self) -> None:
        await self._client.aclose()


def _yes_probability(data: dict[str, Any]) -> float:
    """从首 token 的 top_logprobs 里取 yes/no，返回归一化 P(yes)。

    缺 token（理论上不会发生：judge prompt 的首 token 分布必然包含
    yes/no 之一）时按 0 分处理并留痕，不让单个坏响应打断整批重排。
    """

    logprobs = data.get("logprobs") or []
    if not logprobs:
        logger.warning("Ollama 未返回 logprobs，该候选按 0 分处理")
        return 0.0
    yes: float | None = None
    no: float | None = None
    for candidate in logprobs[0].get("top_logprobs", []):
        token = str(candidate.get("token", "")).strip().lower()
        if token == "yes" and yes is None:  # noqa: S105 —— judge 输出 token，不是口令
            yes = float(candidate["logprob"])
        elif token == "no" and no is None:  # noqa: S105 —— 同上，字面量匹配
            no = float(candidate["logprob"])
    if yes is None and no is None:
        logger.warning("首 token 分布里没有 yes/no，该候选按 0 分处理")
        return 0.0
    p_yes = math.exp(yes) if yes is not None else 0.0
    p_no = math.exp(no) if no is not None else 0.0
    return p_yes / (p_yes + p_no) if (p_yes + p_no) > 0 else 0.0


__all__ = ["OllamaQwen3Reranker"]
