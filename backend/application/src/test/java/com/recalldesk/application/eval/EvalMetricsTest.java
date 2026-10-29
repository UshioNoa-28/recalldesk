package com.recalldesk.application.eval;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.groups.Tuple.tuple;

import com.recalldesk.domain.eval.ChannelScore;
import com.recalldesk.domain.eval.EvalRunItem;
import com.recalldesk.domain.eval.EvalTestSetItem;
import com.recalldesk.domain.eval.EvidenceQuote;
import com.recalldesk.domain.retrieval.ChannelTrace;
import com.recalldesk.domain.retrieval.ChunkHit;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 指标口径的冻结期望：输入是一批构造题，逐项断言判分与聚合的结果。
 *
 * 数值不做任何舍入/截断，直接比对 double 原值（用精确分数表达，避免手写小数尾差）。
 */
class EvalMetricsTest {

    private static ChunkHit hit(String doc, int index, double score) {
        return new ChunkHit(doc, doc + ".md", index, 3, "chunk " + index + " of " + doc, score);
    }

    /** 一个金标：文档 + 块号。 */
    private static EvidenceQuote gold(String documentId, int chunkIndex, int ordinal) {
        return new EvidenceQuote(
                documentId + "#" + chunkIndex, "i", documentId, chunkIndex, ordinal);
    }

    private static EvalTestSetItem question(EvidenceQuote... quotes) {
        return new EvalTestSetItem("i", "q", List.of(quotes));
    }

    @Test
    @DisplayName("判分与聚合：逐字段钉住口径")
    void scoreQueryAndAggregateArePinned() {
        List<Map.Entry<String, EvalRunItem>> scored = new ArrayList<>();
        scored.add(Map.entry("single_evidence_hit_rank3", EvalMetrics.scoreQuery(
                question(gold("d1", 4, 0)),
                List.of(hit("d1", 0, 0.9), hit("d2", 1, 0.8), hit("d1", 4, 0.7), hit("d3", 0, 0.6)),
                5,
                12.5,
                null)));
        scored.add(Map.entry("multi_evidence_partial", EvalMetrics.scoreQuery(
                question(gold("d1", 0, 0), gold("d1", 1, 1), gold("d2", 0, 2)),
                List.of(hit("d1", 1, 0.9), hit("x", 0, 0.85), hit("d1", 1, 0.8), hit("d2", 0, 0.7)),
                5,
                8.25,
                List.of())));
        scored.add(Map.entry("no_evidence_hit", EvalMetrics.scoreQuery(
                question(gold("d1", 9, 0)),
                List.of(hit("d2", 0, 0.5), hit("d3", 1, 0.4)),
                3,
                100.0,
                null)));
        scored.add(Map.entry("truncated_by_k", EvalMetrics.scoreQuery(
                question(gold("d1", 0, 0), gold("d1", 7, 1)),
                List.of(hit("d1", 0, 0.9), hit("z", 0, 0.8), hit("z", 1, 0.7), hit("d1", 7, 0.6)),
                3,
                3.14,
                null)));
        // 一段跨块的引文：命中它覆盖的任一块都算这段找到了（旧的「坐标即金标」表达不了这件事）
        // 多跳题的常态：每个金标是独立的一块，两块都得进 top-k
        scored.add(Map.entry("multi_gold_all_hit", EvalMetrics.scoreQuery(
                question(gold("d1", 0, 0), gold("d1", 1, 1), gold("d2", 5, 2)),
                List.of(hit("d1", 1, 0.9), hit("d2", 5, 0.5), hit("d1", 0, 0.4)),
                10,
                1.0,
                null)));
        scored.add(Map.entry("empty_evidence", EvalMetrics.scoreQuery(
                question(), List.of(hit("d1", 0, 0.9)), 5, 0.0, null)));
        scored.add(Map.entry("with_channels", EvalMetrics.scoreQuery(
                question(gold("d1", 0, 0), gold("d1", 1, 1), gold("d2", 3, 2)),
                List.of(hit("d1", 0, 0.91), hit("d1", 1, 0.82), hit("junk", 0, 0.8)),
                5,
                20.0,
                List.of(
                        new ChannelTrace("dense_original", "原始问句",
                                List.of(hit("d1", 0, 0.9), hit("junk", 0, 0.5)), 12),
                        new ChannelTrace("dense_variant", "改写问句",
                                List.of(hit("d2", 3, 0.95), hit("d1", 1, 0.6), hit("d1", 0, 0.1)), 30),
                        new ChannelTrace("sparse", "关键词",
                                List.of(hit("junk", 9, 12.0), hit("d1", 1, 7.0)), 5)))));

        List<EvalRunItem> mixed = scored.stream().map(Map.Entry::getValue).toList();
        List<EvalRunItem> thirds = List.of(
                new EvalRunItem("a", "q", 1, 12.35, 1, 1, List.of(1), List.of()),
                new EvalRunItem("b", "q", 2, 12.45, 3, 2, List.of(1, 4), List.of()),
                new EvalRunItem("c", "q", null, 125.55, 2, 0, List.of(), List.of()));

        // ---- 逐题判分 ----
        Map<String, EvalRunItem> byName = new LinkedHashMap<>();
        scored.forEach(entry -> byName.put(entry.getKey(), entry.getValue()));

        EvalRunItem rank3 = byName.get("single_evidence_hit_rank3");
        assertThat(rank3.hitRank()).isEqualTo(3);
        // 只有一块证据且它进了 top-k：块级全在，所以 joint_hit=1（名次靠后由 map 惩罚）
        assertThat(EvalMetrics.jointHit(rank3)).isEqualTo(1);
        assertThat(rank3.evidenceRanks()).containsExactly(3);
        assertThat(EvalMetrics.averagePrecision(rank3)).isEqualTo(1.0 / 3, org.assertj.core.data.Offset.offset(1e-12));

        EvalRunItem partial = byName.get("multi_evidence_partial");
        assertThat(partial.evidenceMatched()).isEqualTo(2);
        assertThat(partial.evidenceRanks()).containsExactly(1, 4);
        assertThat(EvalMetrics.jointHit(partial)).isZero();
        assertThat(EvalMetrics.evidenceCoverage(partial)).isEqualTo(2.0 / 3, org.assertj.core.data.Offset.offset(1e-12));

        EvalRunItem missing = byName.get("no_evidence_hit");
        assertThat(missing.hitRank()).isNull();
        assertThat(missing.evidenceRanks()).isEmpty();
        assertThat(EvalMetrics.averagePrecision(missing)).isZero();

        EvalRunItem truncated = byName.get("truncated_by_k");
        assertThat(truncated.evidenceRanks()).containsExactly(1); // 第 4 名被 k=3 截掉
        assertThat(EvalMetrics.jointHit(truncated)).isZero();

        EvalRunItem multi = byName.get("multi_gold_all_hit");
        assertThat(EvalMetrics.jointHit(multi)).isEqualTo(1); // 三块全进 top-k
        assertThat(multi.evidenceRanks()).containsExactly(1, 2, 3);

        EvalRunItem empty = byName.get("empty_evidence");
        assertThat(empty.evidenceTotal()).isZero();
        assertThat(EvalMetrics.jointHit(empty)).isZero();

        EvalRunItem withChannels = byName.get("with_channels");
        assertThat(withChannels.channels()).extracting(ChannelScore::kind)
                .containsExactly("dense_original", "dense_variant", "sparse", "union");
        assertThat(withChannels.channels().getLast().ranks()).containsExactly(1, 1, 2); // union oracle

        // ---- 聚合（原值，不截断；空组给全 0 壳） ----
        Map<String, Object> mixedMetrics = EvalMetrics.aggregate(mixed, 5);
        assertThat(mixedMetrics).containsEntry("recall@5", 2.0 / 7)
                .containsEntry("map@5", 3.0 / 7)
                .containsEntry("evidence_coverage", 0.5476190476190476)
                .containsEntry("queries", 7)
                .containsEntry("avg_latency_ms", 20.698571428571427);

        @SuppressWarnings("unchecked")
        Map<String, Map<String, Object>> buckets =
                (Map<String, Map<String, Object>>) mixedMetrics.get("buckets");
        assertThat(buckets.get("single_hop")).containsEntry("queries", 3)
                .containsEntry("recall@5", 1.0 / 3);
        assertThat(buckets.get("multi_hop")).containsEntry("queries", 4)
                .containsEntry("map@5", 2.0 / 3);

        @SuppressWarnings("unchecked")
        Map<String, Map<String, Object>> channels =
                (Map<String, Map<String, Object>>) mixedMetrics.get("channels");
        assertThat(channels).containsOnlyKeys("dense_original", "dense_variant", "sparse", "union");
        assertThat(channels.get("union")).containsEntry("map@5", 1.5);

        // 空组：三个质量指标与均值都给 0，不返回 null
        assertThat(EvalMetrics.aggregate(List.of(), 10))
                .containsEntry("recall@10", 0.0)
                .containsEntry("map@10", 0.0)
                .containsEntry("evidence_coverage", 0.0)
                .containsEntry("queries", 0)
                .containsEntry("avg_latency_ms", 0.0)
                .containsEntry("buckets", Map.of(
                        "single_hop", Map.of("recall@10", 0.0, "map@10", 0.0,
                                "evidence_coverage", 0.0, "queries", 0),
                        "multi_hop", Map.of("recall@10", 0.0, "map@10", 0.0,
                                "evidence_coverage", 0.0, "queries", 0)));

        Map<String, Object> thirdsMetrics = EvalMetrics.aggregate(thirds, 3);
        assertThat(thirdsMetrics).containsEntry("recall@3", 0.3333333333333333)
                .containsEntry("evidence_coverage", 0.5555555555555555)
                .containsEntry("avg_latency_ms", 50.11666666666667);
    }

    @Test
    @DisplayName("每路耗时随通道一起落库：union 是并集 oracle，没有真实检索，所以它是 null")
    void channelLatencyRidesAlongWithScores() {
        EvalRunItem scored = EvalMetrics.scoreQuery(
                question(gold("d1", 0, 0)),
                List.of(hit("d1", 0, 0.9)),
                5,
                20.0,
                List.of(new ChannelTrace("dense_original", "原始问句", List.of(hit("d1", 0, 0.9)), 12)));

        assertThat(scored.channels())
                .extracting(ChannelScore::kind, ChannelScore::tookMs)
                .containsExactly(tuple("dense_original", 12L), tuple("union", null));
    }

}
