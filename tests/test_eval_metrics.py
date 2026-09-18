"""检索指标单元测试（纯逻辑，离线运行）。

锁住三指标口径（2026-09-15 定稿：recall@k 块级全在 / map@k 名次+噪声 /
coverage 块级比例，文档级宽口径与 mrr、low_recall 已退役）：
k 外无名次（一切指标同一个 top-k 列表）；map 对"挤垃圾/埋得深"打折而
joint 不辨先后；聚合永远带单跳/多跳分桶。
"""

from __future__ import annotations

import unittest
from unittest import TestCase

from app.domain.eval import ChunkRef, EvalItemStatus, EvalRunItem, EvalTestSetItem
from app.domain.eval_metrics import aggregate, score_query


def _hit(document_id: str, chunk_index: int) -> dict:
    return {"document_id": document_id, "chunk_index": chunk_index}


def _item(
    chunk_index: int = 3,
    *,
    document_id: str = "doc-1",
    item_id: str = "item-1",
    evidence: list[ChunkRef] | None = None,
) -> EvalTestSetItem:
    return EvalTestSetItem(
        id=item_id,
        status=EvalItemStatus.READY,
        query="豆腐有多少蛋白质？",
        evidence=(
            evidence if evidence is not None else [ChunkRef(document_id, chunk_index)]
        ),
    )


def _result(
    hit_rank: int | None = 1,
    latency_ms: float = 100.0,
    item_id: str = "item-1",
    *,
    evidence_total: int = 1,
    evidence_matched: int | None = None,
    ranks: list[int] | None = None,
) -> EvalRunItem:
    matched = evidence_matched if evidence_matched is not None else (1 if hit_rank else 0)
    return EvalRunItem(
        testset_item_id=item_id,
        query="问题",
        hit_rank=hit_rank,
        latency_ms=latency_ms,
        evidence_total=evidence_total,
        evidence_matched=matched,
        # 不给 ranks 就模拟 0015 前的老行：map 按 0 计
        evidence_ranks=ranks if ranks is not None else ([hit_rank] if hit_rank else []),
    )


class ScoreQueryTests(TestCase):
    def test_expected_chunk_ranked_first(self) -> None:
        hits = [_hit("doc-1", 3), _hit("doc-2", 0)]

        result = score_query(_item(), hits, k=5, latency_ms=42.15)

        self.assertEqual("item-1", result.testset_item_id)
        self.assertEqual(1, result.hit_rank)
        self.assertEqual([1], result.evidence_ranks)
        self.assertEqual(1, result.joint_hit)
        self.assertEqual(1.0, result.evidence_coverage)
        self.assertEqual(1.0, result.average_precision)
        self.assertEqual(42.15, result.latency_ms)
        # 题面从题目带出来，结果行里不留副本；坐标去 evidence 表查
        self.assertEqual("豆腐有多少蛋白质？", result.query)

    def test_ranked_third_scores_everything(self) -> None:
        hits = [_hit("doc-2", 0), _hit("doc-3", 1), _hit("doc-1", 3)]

        result = score_query(_item(), hits, k=5, latency_ms=1.0)

        self.assertEqual(3, result.hit_rank)
        self.assertEqual(1, result.joint_hit)
        self.assertAlmostEqual(1 / 3, result.average_precision)  # 单证据：map=1/rank

    def test_evidence_outside_top_k_is_nothing(self) -> None:
        """k 外无名次：一切指标都在 top-k 列表内说话（ranks 也钳位到 k）。"""

        hits = [_hit(f"doc-{index}", 0) for index in range(2, 10)]
        hits.append(_hit("doc-1", 3))  # 第 9 名，k=5 看不见

        result = score_query(_item(), hits, k=5, latency_ms=1.0)

        self.assertEqual([], result.evidence_ranks)
        self.assertIsNone(result.hit_rank)
        self.assertEqual(0, result.joint_hit)
        self.assertEqual(0.0, result.average_precision)

    def test_right_document_wrong_chunk_scores_zero(self) -> None:
        """文档级宽口径已退役：同篇别的块进 top-k 不算数，要的块没进就是 0。"""

        hits = [_hit("doc-1", 0), _hit("doc-1", 9)]

        result = score_query(_item(), hits, k=5, latency_ms=1.0)

        self.assertEqual(0, result.joint_hit)
        self.assertIsNone(result.hit_rank)

    def test_duplicate_hit_coords_count_once(self) -> None:
        hits = [_hit("doc-1", 3), _hit("doc-1", 3)]

        result = score_query(_item(), hits, k=5, latency_ms=1.0)

        self.assertEqual([1], result.evidence_ranks)
        self.assertEqual(1, result.evidence_matched)

    def test_total_miss_and_empty_hits(self) -> None:
        for hits in ([_hit("doc-2", 3)], []):
            result = score_query(_item(), hits, k=5, latency_ms=1.0)
            self.assertEqual(0, result.joint_hit)
            self.assertIsNone(result.hit_rank)
            self.assertEqual(0.0, result.evidence_coverage)
            self.assertEqual(0.0, result.average_precision)

    def test_item_without_evidence_scores_zero_everything(self) -> None:
        """平权时代没有主坐标回落：没证据的题各指标全 0，不炸也不编分数。"""

        item = _item(3, evidence=[])
        hits = [_hit("doc-1", 9), _hit("doc-1", 3)]

        result = score_query(item, hits, k=5, latency_ms=1.0)

        self.assertEqual(0, result.evidence_total)
        self.assertIsNone(result.hit_rank)
        self.assertEqual(0, result.joint_hit)
        self.assertEqual(0.0, result.evidence_coverage)
        self.assertEqual(0.0, result.average_precision)


class MultiEvidenceScoreTests(TestCase):
    """多证据题（跨文档 / 同文档多块）的打分口径。"""

    def test_both_back_gives_joint_and_dips_map(self) -> None:
        """两块在 1、4 名：joint=1、coverage=1，但 map 记住埋得深的那块。"""

        item = _item(3, evidence=[ChunkRef("doc-2", 0), ChunkRef("doc-1", 3)])
        hits = [_hit("doc-2", 0), _hit("doc-3", 0), _hit("doc-4", 0), _hit("doc-1", 3)]

        result = score_query(item, hits, k=5, latency_ms=1.0)

        self.assertEqual([1, 4], result.evidence_ranks)
        self.assertEqual(1, result.joint_hit)
        self.assertEqual(0.75, result.average_precision)  # (1/1 + 2/4) / 2

    def test_one_missing_partial_credit(self) -> None:
        item = _item(3, evidence=[ChunkRef("doc-1", 3), ChunkRef("doc-2", 0)])
        hits = [_hit("doc-1", 3), _hit("doc-4", 0), _hit("doc-4", 1)]

        result = score_query(item, hits, k=5, latency_ms=1.0)

        self.assertEqual(0, result.joint_hit)  # 差一块就是答不成
        self.assertEqual(0.5, result.evidence_coverage)
        self.assertEqual(0.5, result.average_precision)  # (1/1) / 2：回来的那块在榜首，缺的摊 0

    def test_same_doc_multiple_chunks_all_required(self) -> None:
        """同文档两块都要：一块回来一块没回来，joint 不给过。"""

        item = _item(7, evidence=[ChunkRef("doc-1", 7), ChunkRef("doc-1", 2)])
        hits = [_hit("doc-1", 2)]

        result = score_query(item, hits, k=5, latency_ms=1.0)

        self.assertEqual(1, result.hit_rank)
        self.assertEqual(0, result.joint_hit)
        self.assertEqual(0.5, result.evidence_coverage)


class AggregateTests(TestCase):
    def test_averages_and_rounding(self) -> None:
        results = [
            _result(hit_rank=2, evidence_matched=1, latency_ms=100.0),
            _result(hit_rank=None, evidence_matched=0, latency_ms=200.17, item_id="item-2"),
        ]

        summary = aggregate(results, k=5)

        self.assertEqual(0.5, summary["recall@5"])  # (1 + 0) / 2
        self.assertEqual(0.25, summary["map@5"])  # (1/2 + 0) / 2
        self.assertEqual(0.5, summary["evidence_coverage"])
        self.assertEqual(150.1, summary["avg_latency_ms"])
        self.assertEqual(2, summary["queries"])

    def test_metric_keys_carry_k(self) -> None:
        """k 写进键名：同一份结果在 k=3 与 k=10 下是两个数字，不能共用一个键。"""

        summary = aggregate([_result()], k=10)
        self.assertIn("recall@10", summary)
        self.assertIn("map@10", summary)

    def test_empty_run_is_zero_not_none(self) -> None:
        summary = aggregate([], k=5)

        shell = {
            "recall@5": 0.0,
            "map@5": 0.0,
            "evidence_coverage": 0.0,
            "queries": 0,
        }
        self.assertEqual(
            shell
            | {
                "avg_latency_ms": 0.0,
                "buckets": {"single_hop": dict(shell), "multi_hop": dict(shell)},
            },
            summary,
        )

    def test_map_penalizes_noise_beyond_joint(self) -> None:
        """两块证据 1、4 名 vs 2、4 名：joint 相同、coverage 相同，map 分高下。"""

        good = _result(hit_rank=1, ranks=[1, 4], evidence_total=2, evidence_matched=2)
        meh = _result(hit_rank=2, ranks=[2, 4], evidence_total=2, evidence_matched=2)

        self.assertEqual(0.75, good.average_precision)  # (1/1 + 2/4) / 2
        self.assertEqual(0.5, meh.average_precision)  # (1/2 + 2/4) / 2
        self.assertEqual(good.joint_hit, meh.joint_hit)  # 都凑齐，二元指标看不见先后

    def test_map_zero_for_legacy_rows_without_ranks(self) -> None:
        """0015 前的老行（ranks=None）按 0 计，不炸聚合。"""

        legacy = EvalRunItem(
            testset_item_id="old",
            query="q",
            hit_rank=1,
            latency_ms=1.0,
        )

        self.assertIsNone(legacy.average_precision)
        self.assertEqual(0.0, aggregate([legacy], k=5)["map@5"])

    def test_buckets_split_by_evidence_count(self) -> None:
        """单跳/多跳分桶：整体被平均稀释的数字在桶里藏不住。"""

        single = _result(hit_rank=1, ranks=[1], evidence_matched=1)  # total 1
        multi_good = _result(
            hit_rank=1, item_id="m1", ranks=[1, 2], evidence_total=2, evidence_matched=2
        )
        multi_bad = _result(
            hit_rank=1, item_id="m2", ranks=[1], evidence_total=2, evidence_matched=1
        )
        summary = aggregate([single, multi_good, multi_bad], k=5)

        single_bucket = summary["buckets"]["single_hop"]
        multi_bucket = summary["buckets"]["multi_hop"]
        self.assertEqual(1, single_bucket["queries"])
        self.assertEqual(2, multi_bucket["queries"])
        self.assertEqual(1.0, single_bucket["recall@5"])
        self.assertEqual(0.5, multi_bucket["recall@5"])  # 一好一坏，均值现出原形
        self.assertEqual(1.0, single_bucket["map@5"])
        self.assertEqual(0.75, multi_bucket["map@5"])  # (1.0 + (1/1)/2) / 2

    def test_recall_keeps_four_decimals(self) -> None:
        results = [_result(item_id=str(index)) for index in range(2)]
        results += [
            _result(hit_rank=None, evidence_matched=0, item_id=str(index))
            for index in range(2, 9)
        ]

        self.assertEqual(0.2222, aggregate(results, k=5)["recall@5"])


if __name__ == "__main__":
    unittest.main()
