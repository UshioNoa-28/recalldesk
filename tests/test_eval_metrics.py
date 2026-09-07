"""检索指标单元测试（纯逻辑，离线运行）。

锁住三件事：recall 看文档、hit_rank 看切片（两个粒度可以给出相反的答案）、
mrr / low_recall 是从这两列派生出来的而不是另算一套。
"""

from __future__ import annotations

import unittest
from unittest import TestCase

from app.domain.eval import EvalItemStatus, EvalRunItem, EvalTestSetItem
from app.domain.eval_metrics import aggregate, score_query


def _hit(document_id: str, chunk_index: int) -> dict:
    return {"document_id": document_id, "chunk_index": chunk_index}


def _item(
    chunk_index: int = 3, *, document_id: str = "doc-1", item_id: str = "item-1"
) -> EvalTestSetItem:
    return EvalTestSetItem(
        id=item_id,
        answer_document_id=document_id,
        answer_chunk_index=chunk_index,
        status=EvalItemStatus.READY,
        query="豆腐有多少蛋白质？",
    )


def _result(
    hit_rank: int | None = 1,
    recall: int = 1,
    latency_ms: float = 100.0,
    item_id: str = "item-1",
) -> EvalRunItem:
    return EvalRunItem(
        testset_item_id=item_id,
        query="问题",
        answer_document_id="doc-1",
        answer_chunk_index=0,
        hit_rank=hit_rank,
        recall=recall,
        latency_ms=latency_ms,
    )


class ScoreQueryTests(TestCase):
    def test_expected_chunk_ranked_first(self) -> None:
        hits = [_hit("doc-1", 3), _hit("doc-2", 0)]

        result = score_query(_item(), hits, k=5, latency_ms=42.15)

        self.assertEqual("item-1", result.testset_item_id)
        self.assertEqual(1, result.hit_rank)
        self.assertEqual(1, result.recall)
        self.assertEqual(1.0, result.mrr)
        self.assertFalse(result.low_recall)
        self.assertEqual(42.15, result.latency_ms)
        # 题面与坐标是从题目带出来的，结果行里不留副本
        self.assertEqual("豆腐有多少蛋白质？", result.query)
        self.assertEqual(3, result.answer_chunk_index)

    def test_expected_chunk_ranked_third(self) -> None:
        hits = [_hit("doc-2", 0), _hit("doc-3", 1), _hit("doc-1", 3)]

        result = score_query(_item(), hits, k=5, latency_ms=1.0)

        self.assertEqual(3, result.hit_rank)
        self.assertEqual(1, result.recall)
        self.assertEqual(1 / 3, result.mrr)

    def test_same_document_other_chunk_hits_recall_but_not_rank(self) -> None:
        """两个粒度的分工：文档进来了就算 recall，切片没被捞回来就没有名次。"""

        hits = [_hit("doc-1", 0), _hit("doc-1", 9)]

        result = score_query(_item(), hits, k=5, latency_ms=1.0)

        self.assertEqual(1, result.recall)
        self.assertIsNone(result.hit_rank)
        self.assertEqual(0.0, result.mrr)

    def test_document_outside_top_k_but_chunk_later_still_scores_mrr(self) -> None:
        """recall 在 k 处截断，mrr 以实际返回列表为界（k 之外仍计名次）。"""

        hits = [_hit(f"doc-{index}", 0) for index in range(2, 10)]
        hits.append(_hit("doc-1", 3))  # 第 9 名

        result = score_query(_item(), hits, k=5, latency_ms=1.0)

        self.assertEqual(0, result.recall)
        self.assertTrue(result.low_recall)
        self.assertEqual(9, result.hit_rank)
        self.assertEqual(1 / 9, result.mrr)

    def test_total_miss(self) -> None:
        result = score_query(_item(), [_hit("doc-2", 3)], k=5, latency_ms=1.0)

        self.assertEqual(0, result.recall)
        self.assertTrue(result.low_recall)
        self.assertIsNone(result.hit_rank)
        self.assertEqual(0.0, result.mrr)

    def test_empty_hits(self) -> None:
        result = score_query(_item(), [], k=5, latency_ms=1.0)

        self.assertEqual(0, result.recall)
        self.assertIsNone(result.hit_rank)


class AggregateTests(TestCase):
    def test_averages_and_rounding(self) -> None:
        results = [_result(hit_rank=2, recall=1, latency_ms=100.0), _result(
            hit_rank=None, recall=0, latency_ms=200.17, item_id="item-2"
        )]

        summary = aggregate(results, k=5)

        self.assertEqual(0.5, summary["recall@5"])
        self.assertEqual(0.25, summary["mrr"])  # (1/2 + 0) / 2
        self.assertEqual(150.1, summary["avg_latency_ms"])
        self.assertEqual(2, summary["queries"])

    def test_metric_key_carries_k(self) -> None:
        """k 写进键名：同一份结果在 k=3 与 k=10 下是两个数字，不能共用一个键。"""

        self.assertIn("recall@10", aggregate([_result()], k=10))

    def test_empty_run_is_zero_not_none(self) -> None:
        summary = aggregate([], k=5)

        self.assertEqual(
            {"recall@5": 0.0, "mrr": 0.0, "avg_latency_ms": 0.0, "queries": 0},
            summary,
        )

    def test_recall_keeps_four_decimals(self) -> None:
        results = [_result(recall=1, item_id=str(index)) for index in range(2)]
        results += [_result(recall=0, item_id=str(index)) for index in range(7)]

        self.assertEqual(0.2222, aggregate(results, k=5)["recall@5"])


if __name__ == "__main__":
    unittest.main()
