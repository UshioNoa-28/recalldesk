"""LlamaIndexLlmClient 单元测试（注入假 LLM，不连真实服务）。"""

from __future__ import annotations

import unittest
from unittest import IsolatedAsyncioTestCase as TestCase
from unittest.mock import AsyncMock, Mock

from app.infrastructure.llama_index_llm_client import LlamaIndexLlmClient


def _fake_llm(content: str | None) -> Mock:
    llm = Mock()
    llm.acomplete = AsyncMock(return_value=Mock(text=content))
    return llm


class LlamaIndexLlmClientTests(TestCase):
    async def test_generate_returns_message_content(self) -> None:
        client = LlamaIndexLlmClient(
            model="test-model", api_base="http://x/v1", api_key="k",
            llm=_fake_llm("改写后的查询"),
        )

        self.assertEqual("改写后的查询", await client.generate("原始查询"))

    async def test_generate_empty_content_becomes_empty_string(self) -> None:
        client = LlamaIndexLlmClient(
            model="test-model", api_base="http://x/v1", api_key="k",
            llm=_fake_llm(None),
        )

        self.assertEqual("", await client.generate("p"))


if __name__ == "__main__":
    unittest.main()
