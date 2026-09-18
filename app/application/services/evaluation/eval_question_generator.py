"""LLM 出题服务：由 chunk 证据集合反向生成用户问题。

单证据题用旧提示词（行为与历史一致）；多证据题换多跳提示词，
要求问题必须综合全部片段才答得出——不然第二块证据就只是摆设。

结构化输出走 LlmClient.generate_structured（纯 prompt 要 JSON + 清洗），
与 QueryRewriteService 一致，兼容各类 OpenAI 兼容中转。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.ports.model_clients.llm_client import LlmClient

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHARS = 1500  # 全部证据的总字符预算（多块时每块分到 预算/块数）
MIN_CHARS_PER_FRAGMENT = 200  # 每块至少留这么多，否则截了也没上下文价值

PROMPT = """根据以下知识库片段，写一个用户可能会问的问题（中文）。

要求：
- 答案必须能在这个片段里找到
- 像真实用户一样口语化提问，不要照抄原文词句
- 只输出问题本身，不要解释、不要加引号

文档：{document_name}

片段：
{text}"""

MULTI_PROMPT = """根据以下 {count} 段知识库资料，写一个用户可能会问的问题（中文）。

要求：
- 回答这个问题需要**综合所有片段**的信息，任何单一片段都不足以完整回答
- 像真实用户一样口语化提问，不要照抄原文词句，不要直接点名片段编号
- 只输出问题本身，不要解释、不要加引号

{fragments}"""


@dataclass(frozen=True)
class QuestionFragment:
    """一段出题素材：坐标 + 原文 + 文档名（拼提示词用）。"""

    document_id: str
    chunk_index: int
    document_name: str
    text: str


class EvalQuestionOutput(BaseModel):
    """LLM 出题的结构化输出。"""

    query: str = Field(min_length=1, description="生成的问题")


class EvalQuestionGenerator:
    """把证据片段集合变成一道题。"""

    def __init__(self, llm_client: LlmClient) -> None:
        self._llm_client = llm_client

    async def generate(self, *, fragments: list[QuestionFragment]) -> str:
        """生成一条问题；空结果视为失败（抛 ValueError，交给任务重试）。"""

        if not fragments:
            raise ValueError("没有可用的出题素材")
        if len(fragments) == 1:
            prompt = PROMPT.format(
                document_name=fragments[0].document_name or "（未知）",
                text=fragments[0].text[:MAX_CONTEXT_CHARS],
            )
        else:
            budget = max(MIN_CHARS_PER_FRAGMENT, MAX_CONTEXT_CHARS // len(fragments))
            blocks = "\n\n".join(
                f"资料 {i}（《{f.document_name or '未知'}》 切片 #{f.chunk_index}）："
                f"\n{f.text[:budget]}"
                for i, f in enumerate(fragments, 1)
            )
            prompt = MULTI_PROMPT.format(count=len(fragments), fragments=blocks)
        output = await self._llm_client.generate_structured(prompt, EvalQuestionOutput)
        query = output.query.strip().strip('"').strip()
        if not query:
            raise ValueError("LLM 返回了空问题")
        return query


__all__ = ["EvalQuestionGenerator", "EvalQuestionOutput", "QuestionFragment"]
