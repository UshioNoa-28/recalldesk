"""llama-index OpenAILike 适配器：把框架实现挂到 LlmClient 端口上。

连任何 OpenAI 兼容端点（OpenAI / Ollama / 各类中转站），
协议适配、重试等由 llama-index 处理；异步走 BaseLLM 原生 acomplete。
"""

from __future__ import annotations

from llama_index.llms.openai_like import OpenAILike
from pydantic import BaseModel

from app.ports.llm_client import LlmClient


class LlamaIndexLlmClient(LlmClient):
    def __init__(
        self,
        *,
        model: str,
        api_base: str,
        api_key: str,
        temperature: float = 0.0,
        timeout: float = 120.0,
        llm: OpenAILike | None = None,
    ) -> None:
        self._llm = llm or OpenAILike(
            model=model,
            api_base=api_base,
            api_key=api_key,
            is_chat_model=True,
            is_function_calling_model=True,
            temperature=temperature,
            timeout=timeout,
        )

    async def generate(self, prompt: str) -> str:
        response = await self._llm.acomplete(prompt)  # acomplete 返回 CompletionResponse
        return response.text or ""

    async def generate_structured(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        """强制按 schema 输出：文本补全 + Pydantic 解析校验。

        刻意不用 tool calling 路线（as_structured_llm）——中转/小模型
        时不时直接回文本不调工具，整批任务会崩；文本路线对任何
        OpenAI 兼容端点都稳。
        """

        from llama_index.core import PromptTemplate
        from llama_index.core.program import LLMTextCompletionProgram

        program = LLMTextCompletionProgram.from_defaults(
            output_cls=schema,
            prompt=PromptTemplate(prompt),
            llm=self._llm,
            verbose=False,
        )
        return await program.acall()


__all__ = ["LlamaIndexLlmClient"]
