"""检索指标（纯函数）：一次 run 的逐题打分与聚合。

口径来自反向出题：题目本来就带着 ground truth 坐标集合（平权证据，无主），
所以打分不需要人工标注、也不需要 LLM 判分，只看检索有没有把那些坐标
捞回来。聚合只留三个质量指标（对齐多跳基准，2026-09-15 定稿）：

- recall@k   块级全在：所有证据块都进了 top-k 才计 1
             （= 2WikiMultihopQA 的 Joint Evidence，对外口径就叫 Recall@k；
             文档级宽口径已裁撤——"找对篇挑错块"在多跳里不该给分）
- map@k      每块证据的名次 + 该处 precision 的平均（MultiHop-RAG 主指标，
             唯一惩罚"证据旁边挤垃圾/埋得深"的）
- coverage   块级比例：捞回几块 / 该几块（全有全无与名次之外的那根刻度）

（mrr 已退役：多 gold 下它只报最好那块，被 map@k 整体替代）

run 用 top_k=k 检索，hits 就是本次的召回边界，于是各名次只可能落在
1..k —— 所有指标说的是同一个列表。聚合时按证据块数分桶（单跳/多跳），
多跳题的真实短板不再被平均数稀释。
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
    """按证据坐标给一道题打分，返回它的运行结果。

    只读 hits 里的 document_id / chunk_index 两个字段：分数、原文都不参与，
    所以换 embedding 模型、换融合方式都不改这里。
    """

    evidence = item.evidence_refs()
    evidence_coords = {(ref.document_id, ref.chunk_index) for ref in evidence}
    # 逐块记名次（升序，k 内）：ranks 是 map 的原料，matched 恒等于它的长度
    ranks: list[int] = []
    seen: set[tuple[str, int]] = set()
    for rank, hit in enumerate(hits[:k], 1):
        coord = (hit["document_id"], hit["chunk_index"])
        if coord in evidence_coords and coord not in seen:
            seen.add(coord)
            ranks.append(rank)
    return EvalRunItem(
        testset_item_id=item.id,
        query=item.query,
        hit_rank=ranks[0] if ranks else None,
        latency_ms=latency_ms,
        evidence_total=len(evidence),
        evidence_matched=len(ranks),
        evidence_ranks=ranks,
    )


def _summary_for(items: list[EvalRunItem], *, k: int) -> dict[str, Any]:
    """一组题 -> 三个质量指标的均值快照；空组给全 0 壳（前端画对比条不必判空）。

    recall@k 就是块级全在（joint）——文档级宽口径已于 0016 退役。
    """

    count = len(items)
    if count == 0:
        return {
            f"recall@{k}": 0.0,
            f"map@{k}": 0.0,
            "evidence_coverage": 0.0,
            "queries": 0,
        }
    return {
        f"recall@{k}": round(sum(item.joint_hit for item in items) / count, 4),
        # map 对 0015 前无名次快照的老行按 0 计（重跑 run 即刷新）
        f"map@{k}": round(sum(item.average_precision or 0.0 for item in items) / count, 4),
        "evidence_coverage": round(sum(item.evidence_coverage for item in items) / count, 4),
        "queries": count,
    }


def aggregate(results: Iterable[EvalRunItem], *, k: int) -> dict[str, Any]:
    """逐题结果 -> 这次 run 的聚合指标（总览 + 单跳/多跳分桶）。

    分桶按证据块数（≤1 为单跳）：多跳题的真实短板不再被平均数稀释；
    跨文档等更细的切法留给前端从逐题数据自算，这里不预设。
    """

    items = list(results)
    singles = [item for item in items if item.evidence_total <= 1]
    multis = [item for item in items if item.evidence_total > 1]
    overall = _summary_for(items, k=k)
    if items:
        overall["avg_latency_ms"] = round(
            sum(item.latency_ms for item in items) / len(items), 1
        )
    else:
        overall["avg_latency_ms"] = 0.0
    overall["buckets"] = {
        "single_hop": _summary_for(singles, k=k),
        "multi_hop": _summary_for(multis, k=k),
    }
    return overall


__all__ = ["aggregate", "score_query"]
