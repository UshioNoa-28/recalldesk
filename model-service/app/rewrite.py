from __future__ import annotations

import json
import logging

from langchain_core.messages import HumanMessage

from app.contracts import RewriteResponse
from app.errors import UpstreamError

logger = logging.getLogger(__name__)

PROMPT = """You are a search query rewriter for hybrid retrieval (dense + BM25).

Given the raw query, produce:
- queries: %d semantically DIVERSE rewrites of the query
  (different phrasings / related aspects / broader-or-narrower formulations;
  same language as the input; preserve original intent, no invented facts)
- keywords: 3-8 high-signal keywords for lexical/BM25 matching
  (entities and terms, no filler words)

Output ONLY JSON:
{"queries": ["...", "..."], "keywords": ["...", "..."]}

Raw query: %s"""

SUFFIX = (
    "\n\n只输出一个符合以下 JSON Schema 的 JSON 对象；"
    "不要解释、不要代码围栏、不要输出任何其他文字：\n"
)

SCHEMA = json.dumps(
    {
        "properties": {
            "queries": {
                "description": "语义多样的检索改写变体",
                "items": {"type": "string"},
                "minItems": 1,
                "title": "Queries",
                "type": "array",
            },
            "keywords": {
                "default": [],
                "description": "BM25 高信号关键词",
                "items": {"type": "string"},
                "title": "Keywords",
                "type": "array",
            },
        },
        "required": ["queries"],
        "title": "QueryRewriteOutput",
        "type": "object",
    },
    ensure_ascii=False,
)


class RewriteError(UpstreamError):
    def __init__(self, message: str, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.__cause__ = cause


def coerce_json(raw: str) -> str:
    """从模型嘴里把 JSON 抠出来：剥围栏，再退而截首尾花括号。"""
    text = raw.strip()
    if text.startswith("```"):
        newline = text.find("\n")
        text = text[newline + 1 :] if newline >= 0 else text[3:]
        trimmed = text.rstrip()
        if trimmed.endswith("```"):
            text = trimmed[:-3]
        text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if text.startswith("{") or (start >= 0 and end > start):
        return text[start : end + 1]
    return text


def _content(response) -> str:
    content = getattr(response, "content", "")
    if isinstance(content, str):
        return content
    # 多模态 content 是块列表；只要 text 块
    return "".join(
        part.get("text", "")
        for part in content or []
        if isinstance(part, dict) and part.get("type") == "text"
    )


def _non_blank(values: list, fallback: str | None) -> list[str]:
    kept = [value.strip() for value in values if isinstance(value, str) and value.strip()]
    if not kept and fallback is not None:
        return [fallback]
    return kept


def parse_rewrite(raw: str, query: str) -> RewriteResponse:
    data = json.loads(coerce_json(raw))
    if not isinstance(data, dict):
        raise ValueError("输出不是 JSON 对象")
    queries = data.get("queries")
    keywords = data.get("keywords", [])
    if not isinstance(queries, list) or not queries:
        raise ValueError("queries 至少要有 1 条")
    if not isinstance(keywords, list):
        raise ValueError("keywords 必须是数组")
    # schema 的 minItems 只管列表长度，挡不住空白字符串；全空白时退回原始查询
    return RewriteResponse(
        queries=_non_blank(queries, query),
        keywords=_non_blank(keywords, None),
    )


async def rewrite_query(chat, retry_chat, query: str, n_variants: int) -> RewriteResponse:
    directive = PROMPT % (n_variants, query) + SUFFIX + SCHEMA
    last_error: Exception | None = None

    for attempt, model in enumerate((chat, retry_chat), start=1):
        try:
            response = await model.ainvoke([HumanMessage(content=directive)])
            return parse_rewrite(_content(response), query)
        except Exception as exc:  # LLM 网络错误与脏输出走同一条重试阶梯
            last_error = exc
            if attempt == 2:
                break
            logger.warning(
                "查询改写第 %s 次失败（%s），抬温重试",
                attempt,
                _brief(str(exc)),
            )

    raise RewriteError(
        f"查询改写失败（两次）: {_brief(str(last_error))}", cause=last_error
    )


def _brief(message: str) -> str:
    return message if len(message) <= 120 else message[:120]
