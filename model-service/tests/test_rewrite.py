from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.rewrite import RewriteError, coerce_json, parse_rewrite, rewrite_query


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"a":1}', '{"a":1}'),
        ('```json\n{"a": 1}\n```', '{"a": 1}'),
        ('```{"a":1}```', '{"a":1}'),
        ('这是回答：{"a": 1} 以上。', '{"a": 1}'),
        ('前言 {"a": {"b": 2}} 后语', '{"a": {"b": 2}}'),
        ("no json here", "no json here"),
        ("{bad", ""),
        ("```", ""),
        ("```json```", "json"),
        ('  \n {"a":1} \n ', '{"a":1}'),
        ("```python\nx = 1\n```", "x = 1"),
        ('{"a": 1}\n{"b": 2}', '{"a": 1}\n{"b": 2}'),
        ('```\n```\n{"a": 1}', '{"a": 1}'),
        ('{"a": "}`"}', '{"a": "}`"}'),
        ("", ""),
    ],
)
def test_coerce_json_matches_reference(raw: str, expected: str):
    assert coerce_json(raw) == expected


def test_parse_maps_variants_and_keywords():
    rewrite = parse_rewrite(
        '{"queries": ["vitamin C content of apples", "apple nutrition facts"], '
        '"keywords": ["apple", "vitamin"]}',
        "苹果维C",
    )
    assert rewrite.queries == ["vitamin C content of apples", "apple nutrition facts"]
    assert rewrite.keywords == ["apple", "vitamin"]


def test_no_keywords_falls_back_to_first_variant():
    rewrite = parse_rewrite('{"queries": ["apple vitamin C"]}', "苹果维C")
    assert rewrite.keywords == []
    # sparseText 的兜底在 Java 侧读 queries[0]，这里只保证关键词为空


def test_whitespace_only_variants_fall_back_to_raw_query():
    rewrite = parse_rewrite('{"queries": ["   ", ""]}', "苹果维C")
    assert rewrite.queries == ["苹果维C"]


def test_whitespace_keywords_are_dropped():
    rewrite = parse_rewrite('{"queries": ["q"], "keywords": [" ", "apple", ""]}', "苹果维C")
    assert rewrite.keywords == ["apple"]


def test_empty_variants_rejected():
    with pytest.raises(ValueError, match="queries 至少要有 1 条"):
        parse_rewrite('{"queries": []}', "苹果维C")
    with pytest.raises(ValueError, match="queries 至少要有 1 条"):
        parse_rewrite("{}", "苹果维C")


class FakeChat:
    def __init__(self, *contents: str):
        self.contents = list(contents)
        self.calls = 0

    async def ainvoke(self, _messages):
        self.calls += 1
        return SimpleNamespace(content=self.contents.pop(0))


async def test_rewrite_retries_on_dirty_output():
    chat = FakeChat("我无法输出 JSON。")
    retry = FakeChat('{"queries": ["q"]}')

    rewrite = await rewrite_query(chat, retry, "问", 3)

    assert rewrite.queries == ["q"]
    assert chat.calls == 1
    assert retry.calls == 1


async def test_rewrite_raises_after_two_failures():
    chat = FakeChat("没 JSON")
    retry = FakeChat("还是没 JSON")

    with pytest.raises(RewriteError):
        await rewrite_query(chat, retry, "问", 3)
