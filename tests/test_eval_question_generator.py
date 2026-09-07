"""EvalQuestionGenerator 出题服务测试（fake LLM client）。"""

from __future__ import annotations

from unittest import IsolatedAsyncioTestCase

from app.application.services.eval_question_generator import (
    EvalQuestionGenerator,
    EvalQuestionOutput,
)
from app.ports.llm_client import LlmClient


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


class EvalQuestionGeneratorTests(IsolatedAsyncioTestCase):
    async def test_strips_whitespace_and_quotes(self) -> None:
        llm = FakeLlmClient(output=EvalQuestionOutput(query='  "什么是 RAG？" \n'))
        generator = EvalQuestionGenerator(llm_client=llm)

        query = await generator.generate(context_text="片段", document_name="notes.md")

        self.assertEqual("什么是 RAG？", query)

    async def test_prompt_contains_context_and_document_name(self) -> None:
        llm = FakeLlmClient(output=EvalQuestionOutput(query="问题"))
        generator = EvalQuestionGenerator(llm_client=llm)

        await generator.generate(context_text="片段内容", document_name="notes.md")

        self.assertIn("片段内容", llm.prompts[0])
        self.assertIn("notes.md", llm.prompts[0])

    async def test_truncates_long_context(self) -> None:
        llm = FakeLlmClient(output=EvalQuestionOutput(query="问题"))
        generator = EvalQuestionGenerator(llm_client=llm)

        await generator.generate(context_text="字" * 5000, document_name="d")

        self.assertLessEqual(len(llm.prompts[0]), 3000)

    async def test_empty_query_raises(self) -> None:
        llm = FakeLlmClient(output=EvalQuestionOutput(query="   "))
        generator = EvalQuestionGenerator(llm_client=llm)

        with self.assertRaises(ValueError):
            await generator.generate(context_text="片段", document_name="d")

    async def test_llm_error_propagates(self) -> None:
        llm = FakeLlmClient(error=RuntimeError("llm down"))
        generator = EvalQuestionGenerator(llm_client=llm)

        with self.assertRaises(RuntimeError):
            await generator.generate(context_text="片段", document_name="d")


if __name__ == "__main__":
    import unittest

    unittest.main()
