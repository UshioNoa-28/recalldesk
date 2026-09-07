"""LLM 出题服务：由 chunk 快照反向生成用户问题。

结构化输出走 LLMTextCompletionProgram（text 路由），
与 QueryRewriteService 一致，兼容小模型 / OpenAI 兼容中转。
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app.ports.llm_client import LlmClient

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHARS = 1500  # 截断过长的 chunk，控制 token 消耗

PROMPT = """根据以下知识库片段，写一个用户可能会问的问题（中文）。

要求：
- 答案必须能在这个片段里找到
- 像真实用户一样口语化提问，不要照抄原文词句
- 只输出问题本身，不要解释、不要加引号

文档：{document_name}

片段：
{text}"""


class EvalQuestionOutput(BaseModel):
    """LLM 出题的结构化输出。"""

    query: str = Field(min_length=1, description="生成的问题")


class EvalQuestionGenerator:
    """把 chunk 快照变成一道题。"""

    def __init__(self, llm_client: LlmClient) -> None:
        self._llm_client = llm_client

    async def generate(self, *, context_text: str, document_name: str) -> str:
        """生成一条问题；空结果视为失败（抛 ValueError，交给任务重试）。"""

        prompt = PROMPT.format(
            document_name=document_name or "（未知）",
            text=context_text[:MAX_CONTEXT_CHARS],
        )
        output = await self._llm_client.generate_structured(prompt, EvalQuestionOutput)
        query = output.query.strip().strip('"').strip()
        if not query:
            raise ValueError("LLM 返回了空问题")
        return query


__all__ = ["EvalQuestionGenerator", "EvalQuestionOutput"]
