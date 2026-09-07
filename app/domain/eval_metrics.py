"""检索指标（纯函数）：一次 run 的逐题打分与聚合。

口径来自反向出题：题目本来就带着 ground truth 坐标 (document_id,
chunk_index)，所以打分不需要人工标注、也不需要 LLM 判分，只看检索有没有把
那个坐标捞回来。两个粒度刻意不同：

- recall 看**文档**：top-k 里有这篇就算对。问答场景真正要保证的是相关内容
  进得了上下文，同文档的别的切片往往也答得上来。
- hit_rank 看**切片**：期望那块排在第几名。名次比「第几名之内进 top-k」更能
  说明排序质量，所以 mrr 由它算。

run 用 top_k=k 检索，hits 就是本次的召回边界，于是 hit_rank 只可能落在
1..k —— recall@k 与 mrr 说的是同一个列表。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.domain.eval import EvalRunItem, EvalTestSetItem


def score_query(
    item: EvalTestSetItem,
    hits: list[dict],
    *,
    k: int,
    latency_ms: float,
) -> EvalRunItem:
    """按坐标给一道题打分，返回它的运行结果。

    只读 hits 里的 document_id / chunk_index 两个字段：分数、原文都不参与，
    所以换 embedding 模型、换融合方式都不改这里。
    """

    document_id = item.answer_document_id
    return EvalRunItem(
        testset_item_id=item.id,
        query=item.query,
        answer_document_id=document_id,
        answer_chunk_index=item.answer_chunk_index,
        hit_rank=next(
            (
                rank
                for rank, hit in enumerate(hits, 1)
                if hit["document_id"] == document_id
                and hit["chunk_index"] == item.answer_chunk_index
            ),
            None,
        ),
        recall=1 if any(h["document_id"] == document_id for h in hits[:k]) else 0,
        latency_ms=latency_ms,
    )


def aggregate(results: Iterable[EvalRunItem], *, k: int) -> dict[str, Any]:
    """逐题结果 -> 这次 run 的聚合指标。空集各指标给 0 而不是 None。

    recall / mrr 保留 4 位（它们都是 0..1 的均值），延迟保留 1 位。
    """

    items = list(results)
    count = len(items)
    if count == 0:
        return {f"recall@{k}": 0.0, "mrr": 0.0, "avg_latency_ms": 0.0, "queries": 0}

    return {
        f"recall@{k}": round(sum(item.recall for item in items) / count, 4),
        "mrr": round(sum(item.mrr for item in items) / count, 4),
        "avg_latency_ms": round(sum(item.latency_ms for item in items) / count, 1),
        "queries": count,
    }


__all__ = ["aggregate", "score_query"]
