"""llama-index OpenAILike adapter：连任何 OpenAI 兼容端点（中转/Ollama /v1）。

结构化输出走**纯文本 JSON + 清洗**（2026-09-15 裁决）：laneai/deepseek
对 tool calling 的兑现率实测约零（"0 tool calls"频发，且同请求重敲大概率
复现），而对"只输出 JSON"的文本服从率稳定得多——工具路线
（astructured_predict）整体退役，本客户端不再有任何 function calling。

清洗阶梯：剥 ``` 围栏 → 截取首尾花括号（容忍前言后语）→ 解析失败抬温
重试一次 → 两级全败抛给消费链任务级退避。

thinking 污染输出时用 settings.LLM_EXTRA_BODY 传 {"enable_thinking": false}
（OpenAILike.additional_kwargs → extra_body）。
"""

from __future__ import annotations

import json
import logging

from llama_index.llms.openai_like import OpenAILike
from pydantic import BaseModel

from app.ports.model_clients.llm_client import LlmClient

logger = logging.getLogger(__name__)

_SUFFIX = (
    "\n\n只输出一个符合以下 JSON Schema 的 JSON 对象；"
    "不要解释、不要代码围栏、不要输出任何其他文字：\n"
)


def _coerce_json(raw: str) -> str:
    """从模型嘴里把 JSON 抠出来：剥围栏，再退而截首尾花括号。"""

    t = raw.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
        t = t.strip()
    start, end = t.find("{"), t.rfind("}")
    if t.startswith("{") or (start != -1 and end > start):
        return t[start : end + 1]
    return t


class LlamaIndexLlmClient(LlmClient):
    def __init__(
        self,
        *,
        model: str,
        api_base: str,
        api_key: str,
        temperature: float = 0.0,
        timeout: float = 120.0,
        extra_body: dict[str, object] | None = None,
        llm: OpenAILike | None = None,
    ) -> None:
        self._temperature = temperature
        self._extra_body = dict(extra_body) if extra_body else {}
        self._llm = llm or OpenAILike(
            model=model,
            api_base=api_base,
            api_key=api_key or "EMPTY",  # openai 客户端要求非空
            is_chat_model=True,
            temperature=temperature,
            timeout=timeout,
            # additional_kwargs 会被 _get_model_kwargs 并进 chat.completions.create
            additional_kwargs={"extra_body": dict(extra_body)} if extra_body else {},
        )

    async def _content(self, prompt: str, *, temperature: float | None = None) -> str:
        """Direct SDK chat call, bypassing llama-index response mapping.

        Some relays answer with `"role": ""`, which llama-index turns into a
        ChatMessage validation error; the raw SDK does not care and we only
        need `content` anyway (pure-prompt JSON lane).
        """

        client = self._llm._get_aclient()  # deliberate SDK-level call, see docstring
        kwargs: dict[str, object] = {
            "model": self._llm.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self._temperature if temperature is None else temperature,
        }
        if self._extra_body:
            kwargs["extra_body"] = self._extra_body
        response = await client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""

    async def generate(self, prompt: str) -> str:
        return await self._content(prompt)

    async def generate_structured(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        """纯 prompt 路线：文本要 JSON + 清洗；常温、抬温各一次，全败抛给退避。"""

        directive = (
            prompt
            + _SUFFIX
            + json.dumps(schema.model_json_schema(), ensure_ascii=False)
        )
        attempts = ({}, {"temperature": 0.8})
        for attempt, kwargs in enumerate(attempts, start=1):
            try:
                raw = await self._content(directive, **kwargs)
                return schema.model_validate_json(_coerce_json(raw))
            except (ValueError, TypeError) as exc:  # pydantic 是 ValueError 系
                last_try = attempt == len(attempts)
                logger.warning(
                    "文本 JSON 解析失败（第 %d 次，%s），%s",
                    attempt,
                    str(exc)[:80],
                    "交任务级退避" if last_try else "抬温重试",
                )
                if last_try:
                    raise


__all__ = ["LlamaIndexLlmClient"]
