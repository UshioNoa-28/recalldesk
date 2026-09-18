"""EvalQuestionGenerator 出题服务测试（fake LLM client）。"""

from __future__ import annotations

from unittest import IsolatedAsyncioTestCase

from app.application.services.evaluation.eval_question_generator import (
    MAX_CONTEXT_CHARS,
    EvalQuestionGenerator,
    EvalQuestionOutput,
    QuestionFragment,
)
from app.ports.model_clients.llm_client import LlmClient


class FakeLlmClient(LlmClient):
    """只实现 generate_structured；返回预设的 pydantic 对象。"""

    def __init__(
        self, output: EvalQuestionOutput | None = None, error: Exception | None = None
    ) -> None:
        self.output = output
        self.error = error
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> str:
        raise NotImplementedError

    async def generate_structured(self, prompt: str, schema):
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return self.output


def _fragment(
    text: str = "片段", name: str = "notes.md", doc: str = "doc-1", index: int = 0
) -> QuestionFragment:
    return QuestionFragment(document_id=doc, chunk_index=index, document_name=name, text=text)


class EvalQuestionGeneratorTests(IsolatedAsyncioTestCase):
    async def test_strips_whitespace_and_quotes(self) -> None:
        llm = FakeLlmClient(output=EvalQuestionOutput(query='  "什么是 RAG？" \n'))
        generator = EvalQuestionGenerator(llm_client=llm)

        query = await generator.generate(fragments=[_fragment()])

        self.assertEqual("什么是 RAG？", query)

    async def test_single_fragment_uses_legacy_prompt(self) -> None:
        """单证据题的提示词与历史一致（文档：/片段：两个锚点）。"""

        llm = FakeLlmClient(output=EvalQuestionOutput(query="问题"))
        generator = EvalQuestionGenerator(llm_client=llm)

        await generator.generate(fragments=[_fragment(text="片段内容")])

        self.assertIn("片段内容", llm.prompts[0])
        self.assertIn("notes.md", llm.prompts[0])
        self.assertIn("文档：", llm.prompts[0])

    async def test_multi_fragments_use_multi_hop_prompt(self) -> None:
        """多证据题换提示词：要求综合全部片段，每块带出处抬头。"""

        llm = FakeLlmClient(output=EvalQuestionOutput(query="问题"))
        generator = EvalQuestionGenerator(llm_client=llm)

        await generator.generate(
            fragments=[
                _fragment(text="苹果富含维C", name="营养指南.txt", index=0),
                _fragment(text="维C有助吸收铁", name="贫血手册.txt", doc="doc-2", index=3),
            ]
        )

        prompt = llm.prompts[0]
        self.assertIn("综合所有片段", prompt)
        self.assertIn("资料 1（《营养指南.txt》 切片 #0）：\n苹果富含维C", prompt)
        self.assertIn("资料 2（《贫血手册.txt》 切片 #3）：\n维C有助吸收铁", prompt)

    async def test_multi_fragments_split_char_budget(self) -> None:
        """每块截到 预算/块数：总提示词不会随证据数线性膨胀。"""

        llm = FakeLlmClient(output=EvalQuestionOutput(query="问题"))
        generator = EvalQuestionGenerator(llm_client=llm)
        n = 3
        budget = MAX_CONTEXT_CHARS // n

        await generator.generate(
            fragments=[_fragment(text="字" * (budget + 500), index=i) for i in range(n)]
        )

        prompt = llm.prompts[0]
        self.assertIn("字" * budget, prompt)
        self.assertNotIn("字" * (budget + 1), prompt)

    async def test_truncates_long_context(self) -> None:
        llm = FakeLlmClient(output=EvalQuestionOutput(query="问题"))
        generator = EvalQuestionGenerator(llm_client=llm)

        await generator.generate(fragments=[_fragment(text="字" * 5000)])

        self.assertLessEqual(len(llm.prompts[0]), 3000)

    async def test_empty_fragments_raises(self) -> None:
        llm = FakeLlmClient(output=EvalQuestionOutput(query="问题"))
        generator = EvalQuestionGenerator(llm_client=llm)

        with self.assertRaises(ValueError):
            await generator.generate(fragments=[])

    async def test_empty_query_raises(self) -> None:
        llm = FakeLlmClient(output=EvalQuestionOutput(query="   "))
        generator = EvalQuestionGenerator(llm_client=llm)

        with self.assertRaises(ValueError):
            await generator.generate(fragments=[_fragment()])

    async def test_llm_error_propagates(self) -> None:
        llm = FakeLlmClient(error=RuntimeError("llm down"))
        generator = EvalQuestionGenerator(llm_client=llm)

        with self.assertRaises(RuntimeError):
            await generator.generate(fragments=[_fragment()])


if __name__ == "__main__":
    import unittest

    unittest.main()
