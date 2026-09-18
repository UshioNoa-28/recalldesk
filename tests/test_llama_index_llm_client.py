"""LlamaIndexLlmClient 单元测试（注入假 OpenAILike，不连真实端点）。"""

from __future__ import annotations

import unittest
from unittest import IsolatedAsyncioTestCase as TestCase
from unittest.mock import AsyncMock, Mock

from pydantic import BaseModel

from app.infrastructure.model_clients.llama_index_llm_client import LlamaIndexLlmClient


class Out(BaseModel):
    """结构化结果。"""

    query: str


def _llm(*contents: str | None) -> Mock:
    """假 OpenAILike：底层 SDK client 按序吐出 contents。

    客户端现在直调 `_get_aclient().chat.completions.create`（绕开 llama-index 的
    role 校验：中转会返回 role=""），所以假件也在这层。
    """

    llm = Mock()
    llm.model = "m"
    completions = Mock()
    completions.create = AsyncMock(
        side_effect=[Mock(choices=[Mock(message=Mock(content=c))]) for c in contents]
    )
    llm._get_aclient.return_value.chat.completions = completions
    llm.astructured_predict = AsyncMock()
    return llm


class LlamaIndexLlmClientTests(TestCase):
    async def test_generate_uses_chat_message_content(self) -> None:
        client = LlamaIndexLlmClient(
            model="m", api_base="http://x/v1", api_key="k", llm=_llm("改写后的查询")
        )
        self.assertEqual("改写后的查询", await client.generate("原始查询"))

    async def test_generate_none_content_becomes_empty_string(self) -> None:
        client = LlamaIndexLlmClient(
            model="m", api_base="http://x/v1", api_key="k", llm=_llm(None)
        )
        self.assertEqual("", await client.generate("p"))

    async def test_generate_structured_text_route_never_touches_tools(self) -> None:
        llm = _llm('{"query": "苹果有什么营养"}')
        client = LlamaIndexLlmClient(model="m", api_base="http://x/v1", api_key="k", llm=llm)

        got = await client.generate_structured("提示词", Out)

        self.assertEqual("苹果有什么营养", got.query)
        self.assertEqual(1, llm._get_aclient.return_value.chat.completions.create.await_count)
        llm.astructured_predict.assert_not_awaited()
        create = llm._get_aclient.return_value.chat.completions.create
        directive = create.await_args.kwargs["messages"][0]["content"]
        self.assertIn("JSON Schema", directive)
        self.assertIn("提示词", directive)  # 原提示词保留

    async def test_generate_structured_coerces_fenced_and_gossipy_json(self) -> None:
        llm = _llm('好的，结果如下：\n```json\n{"query": "兜底"}\n```\n希望有帮助')
        client = LlamaIndexLlmClient(model="m", api_base="http://x/v1", api_key="k", llm=llm)

        got = await client.generate_structured("p", Out)

        self.assertEqual("兜底", got.query)

    async def test_generate_structured_retries_once_raised_temperature(self) -> None:
        llm = _llm("抱歉，我无法完成", '{"query": "苹果有什么营养"}')
        client = LlamaIndexLlmClient(model="m", api_base="http://x/v1", api_key="k", llm=llm)

        got = await client.generate_structured("p", Out)

        self.assertEqual("苹果有什么营养", got.query)
        self.assertEqual(2, llm._get_aclient.return_value.chat.completions.create.await_count)
        # 第二次必须换了采样参数（temp=0 重试是无效动作）
        create = llm._get_aclient.return_value.chat.completions.create
        self.assertEqual(0.8, create.await_args_list[1].kwargs["temperature"])

    async def test_generate_structured_raises_after_two_text_failures(self) -> None:
        llm = _llm("不是 JSON", "还是不是 JSON")
        client = LlamaIndexLlmClient(model="m", api_base="http://x/v1", api_key="k", llm=llm)

        with self.assertRaises(ValueError):
            await client.generate_structured("p", Out)
        llm.astructured_predict.assert_not_awaited()  # 工具路线已整体退役

    def test_extra_body_flows_into_additional_kwargs(self) -> None:
        client = LlamaIndexLlmClient(
            model="m",
            api_base="http://x/v1",
            api_key="k",
            extra_body={"enable_thinking": False},
        )
        self.assertEqual(
            {"extra_body": {"enable_thinking": False}},
            client._llm.additional_kwargs,
        )

    def test_no_extra_body_keeps_kwargs_empty(self) -> None:
        client = LlamaIndexLlmClient(model="m", api_base="http://x/v1", api_key="k")
        self.assertEqual({}, client._llm.additional_kwargs)


if __name__ == "__main__":
    unittest.main()
