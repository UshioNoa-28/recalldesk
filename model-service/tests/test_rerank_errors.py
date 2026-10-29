from __future__ import annotations

import httpx
import pytest

from app.config import settings
from app.errors import UpstreamError
from app.rerank import rerank_scores, score_one


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr("app.rerank.asyncio.sleep", _no_sleep)


def client_with(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_retryable_5xx_is_retried_then_scored():
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, text="cold load")
        return httpx.Response(
            200,
            json={
                "logprobs": [
                    {
                        "top_logprobs": [
                            {"token": "yes", "logprob": -0.5},
                            {"token": "no", "logprob": -2.0},
                        ]
                    }
                ]
            },
        )

    async with client_with(handler) as client:
        score = await score_one(client, settings, "年假几天", "年假为 98 天")

    assert score == pytest.approx(0.8175744761936437, abs=1e-12)
    assert calls == 2


async def test_three_failures_fall_back_to_zero():
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(500, text="boom")

    async with client_with(handler) as client:
        score = await score_one(client, settings, "q", "doc")

    assert score == 0.0
    assert calls == 3


async def test_4xx_propagates_instead_of_scoring_zero():
    def handler(_request):
        return httpx.Response(400, text="bad request")

    async with client_with(handler) as client:
        with pytest.raises(UpstreamError, match="HTTP 400"):
            await score_one(client, settings, "q", "doc")


async def test_empty_documents_short_circuit():
    def handler(_request):  # pragma: no cover - 不应被调用
        raise AssertionError("empty documents must not hit Ollama")

    async with client_with(handler) as client:
        assert await rerank_scores(client, settings, "q", []) == []
