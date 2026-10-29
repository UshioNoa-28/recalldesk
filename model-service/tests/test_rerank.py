from __future__ import annotations

from app.rerank import PROMPT_TEMPLATE, yes_probability


def test_prompt_disables_thinking():
    prompt = PROMPT_TEMPLATE % ("年假几天", "年假为 98 天")
    assert prompt.endswith("<|im_start|>assistant\n<think>\n\n</think>\n\n")


def payload(*token_and_logprob):
    entries = [
        {"token": token_and_logprob[i], "logprob": token_and_logprob[i + 1]}
        for i in range(0, len(token_and_logprob), 2)
    ]
    return {"logprobs": [{"top_logprobs": entries}]}


def test_yes_and_no_normalized():
    assert yes_probability(payload("no", -2.0, "yes", -0.5)) == pytest_approx(
        0.8175744761936437
    )


def test_one_sided():
    assert yes_probability(payload("yes", -1.25)) == 1.0
    assert yes_probability(payload(" no ", -0.25)) == 0.0


def test_token_case_and_spaces_ignored():
    assert yes_probability(payload("maybe", -0.1, "YES", -0.2)) == 1.0
    assert yes_probability(payload("Yes", -0.75, "NO", -1.5)) == pytest_approx(
        0.679178699175393
    )


def test_first_occurrence_wins():
    assert yes_probability(
        payload("yes", -3.0, "yes", -0.125, "no", -0.5)
    ) == pytest_approx(0.07585818002124355)


def test_missing_logprobs_scores_zero():
    assert yes_probability({"logprobs": []}) == 0.0
    assert yes_probability({}) == 0.0
    assert yes_probability(payload("maybe", -0.1)) == 0.0


def pytest_approx(value: float) -> float:
    import pytest

    return pytest.approx(value, abs=1e-12)
