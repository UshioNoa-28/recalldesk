"""LLM 客户端端口。"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class LlmClient(Protocol):
    """单轮文本生成能力（query rewrite 等检索侧功能的基础设施）。"""

    async def generate(self, prompt: str) -> str:
        """给定完整 prompt，返回模型生成的文本。"""
        ...

    async def generate_structured(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        """强制模型按 schema（Pydantic 模型）输出，返回解析后的实例。

        底层走 OpenAI 协议的结构化输出（json_schema / tool calling），
        输出不符号 schema 时由实现抛错，不做静默回退。
        """
        ...


__all__ = ["LlmClient"]
