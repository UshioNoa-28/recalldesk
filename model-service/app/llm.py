from __future__ import annotations

import json

from langchain_openai import ChatOpenAI

from app.config import Settings

RAISED_TEMPERATURE = 0.8


def build_chat_models(settings: Settings) -> tuple[ChatOpenAI | None, ChatOpenAI | None]:
    """按配置建两档温度：第一次求稳，第二次抬温换一个分布。"""
    if not settings.rewrite_enabled:
        return None, None

    kwargs: dict = {
        "model": settings.llm_model,
        "base_url": settings.llm_base_url,
        # openai 客户端要求非空 key；中转大多不校验，但空串会被某些端点直接拒掉
        "api_key": settings.llm_api_key.strip() or "EMPTY",
        "temperature": settings.llm_temperature,
        "timeout": settings.llm_timeout_seconds,
    }
    if settings.llm_extra_body.strip():
        # 等价于 openai SDK 的 extra_body：思考型模型常需 {"enable_thinking": false}
        kwargs["extra_body"] = json.loads(settings.llm_extra_body)

    return ChatOpenAI(**kwargs), ChatOpenAI(**{**kwargs, "temperature": RAISED_TEMPERATURE})
