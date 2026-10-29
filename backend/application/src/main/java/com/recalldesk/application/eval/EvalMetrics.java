package com.recalldesk.application.eval;

import com.recalldesk.domain.eval.ChannelScore;
import com.recalldesk.domain.eval.EvalRunItem;
import com.recalldesk.domain.eval.EvalTestSetItem;
import com.recalldesk.domain.eval.EvidenceQuote;
import com.recalldesk.domain.retrieval.ChannelTrace;
import com.recalldesk.domain.retrieval.ChunkHit;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 评测指标：把逐题检索结果算成 recall@k / map@k / evidence_coverage，再聚合成 run 的总览。
 *
 * 三个指标的口径：
 * - recall@k：本题要求的金标块全部进了前 k 名，记 1，否则 0。
 * - map@k：第 i 个被找回的金标排在第 rank_i 名时，累加 i / rank_i，再除以金标总数（没找回的按 0 计）。
 * - evidence_coverage：找回的金标数 / 要求的金标数。
 */
public final class EvalMetrics {

    private EvalMetrics() {}

    /**
     * 按金标 chunk 给一道题打分，返回它的运行结果。
     *
     * 判分目标是**金标数**：每个 (document_id, chunk_index) 都是一个必中目标
     * （{@link EvidenceQuote#matches}）。名次按金标 id 记账，所以同一块被写成两条金标时
     * 各算一分——那是用户自己指定了两次，不是系统去重的事。
     *
     * channels 是融合前每路的检索轨迹（hits 已按本路分数降序）：逐路算同一套证据名次，
     * 再并集出 union oracle——各路合起来都够不到的题才是上游（索引/数据）的锅，不是改写的锅。
     */
    public static EvalRunItem scoreQuery(
            EvalTestSetItem item, List<ChunkHit> hits, int k, double latencyMs, List<ChannelTrace> channels) {
        List<EvidenceQuote> units = item.evidence();

        List<Integer> ranks = sortedRanks(quoteRanks(units, hits, k));
        List<ChannelScore> channelRows = new ArrayList<>();
        if (channels != null && !channels.isEmpty()) {
            List<Map<String, Integer>> maps = new ArrayList<>();
            for (ChannelTrace trace : channels) {
                Map<String, Integer> rankMap = quoteRanks(units, trace.hits(), k);
                maps.add(rankMap);
                channelRows.add(new ChannelScore(trace.kind(), trace.text(), sortedRanks(rankMap), trace.tookMs()));
            }
            // union oracle：跨通道取每段证据的最优名次（并集里没有 = 谁都够不到）
            channelRows.add(new ChannelScore("union", null, sortedRanks(unionOf(maps)), null));
        }
        return new EvalRunItem(
                item.id(),
                item.query(),
                ranks.isEmpty() ? null : ranks.get(0),
                latencyMs,
                units.size(),
                ranks.size(),
                ranks,
                channelRows);
    }

    /** 跨通道取每段证据的最优名次；并集里缺席 = 所有路都够不到。 */
    private static Map<String, Integer> unionOf(List<Map<String, Integer>> maps) {
        Map<String, Integer> union = new LinkedHashMap<>();
        for (Map<String, Integer> rankMap : maps) {
            rankMap.forEach((quoteId, rank) -> union.merge(quoteId, rank, Math::min));
        }
        return union;
    }

    /**
     * 逐题结果 → 这次 run 的聚合指标（总览 + 单跳/多跳分桶 + 逐通道）。
     *
     * 分桶按证据段数（≤1 为单跳）；跨文档等更细的切法留给前端从逐题数据自算，这里不预设。
     */
    public static Map<String, Object> aggregate(List<EvalRunItem> results, int k) {
        List<EvalRunItem> items = new ArrayList<>(results);
        List<EvalRunItem> singles = items.stream().filter(item -> item.evidenceTotal() <= 1).toList();
        List<EvalRunItem> multis = items.stream().filter(item -> item.evidenceTotal() > 1).toList();
        Map<String, Object> overall = new LinkedHashMap<>(summary(items, k));
        // 固定从左到右累加，别改成补偿求和（Kahan）——末位会漂，历史指标就对不上了
        double latencySum = items.stream().mapToDouble(EvalRunItem::latencyMs).sum();
        overall.put("avg_latency_ms", items.isEmpty() ? 0.0 : latencySum / items.size());
        Map<String, Object> buckets = new LinkedHashMap<>();
        buckets.put("single_hop", summary(singles, k));
        buckets.put("multi_hop", summary(multis, k));
        overall.put("buckets", buckets);
        overall.put("channels", channelSummary(items, k));
        return overall;
    }

    /** 一组题 -> 三个质量指标的均值快照；空组给全 0 壳（前端画对比条不必判空）。 */
    private static Map<String, Object> summary(List<EvalRunItem> items, int k) {
        int count = items.size();
        Map<String, Object> summary = new LinkedHashMap<>();
        if (count == 0) {
            summary.put("recall@" + k, 0.0);
            summary.put("map@" + k, 0.0);
            summary.put("evidence_coverage", 0.0);
            summary.put("queries", 0);
            return summary;
        }
        double recall = items.stream().mapToInt(EvalMetrics::jointHit).sum() / (double) count;
        double map = items.stream().mapToDouble(EvalMetrics::averagePrecision).sum() / count;
        double coverage = items.stream().mapToDouble(EvalMetrics::evidenceCoverage).sum() / count;
        summary.put("recall@" + k, recall);
        summary.put("map@" + k, map);
        summary.put("evidence_coverage", coverage);
        summary.put("queries", count);
        return summary;
    }

    /**
     * 按通道 kind 分桶的逐路汇总（query rewrite 节点评估的 run 级数字）。
     *
     * dense_variant 把所有变体通道当一池统计（变体序号跨题无意义）；
     * union 是 oracle 上界，与融合结果的差 = RRF/融合的调优空间。
     */
    private static Map<String, Object> channelSummary(List<EvalRunItem> items, int k) {
        // 首次出现的插入序（落库后 jsonb 会按库的规则重排，出参不受影响）
        Map<String, List<EvalRunItem>> buckets = new LinkedHashMap<>();
        for (EvalRunItem item : items) {
            for (ChannelScore channel : item.channels()) {
                buckets.computeIfAbsent(channel.kind(), kind -> new ArrayList<>()).add(asChannel(item, channel));
            }
        }
        Map<String, Object> result = new LinkedHashMap<>();
        buckets.forEach((kind, bucket) -> result.put(kind, summary(bucket, k)));
        return result;
    }

    /** 前 k 个命中里哪些金标被找回、各排第几（1 起）；同一块重复命中取最先的名次。 */
    private static Map<String, Integer> quoteRanks(List<EvidenceQuote> units, List<ChunkHit> hits, int k) {
        Map<String, Integer> ranks = new LinkedHashMap<>();
        int limit = Math.min(k, hits.size());
        for (int index = 0; index < limit; index++) {
            ChunkHit hit = hits.get(index);
            for (EvidenceQuote unit : units) {
                if (!ranks.containsKey(unit.id()) && unit.matches(hit.documentId(), hit.chunkIndex())) {
                    ranks.put(unit.id(), index + 1);
                }
            }
        }
        return ranks;
    }

    /** 块级全在：要求的金标全部命中记 1。 */
    public static int jointHit(EvalRunItem item) {
        return item.evidenceTotal() > 0 && item.evidenceMatched() == item.evidenceTotal() ? 1 : 0;
    }

    /** 单题 MAP 原料：Σ(第 i 个找回的块处 i/rank_i) / 金标总数。 */
    public static double averagePrecision(EvalRunItem item) {
        if (item.evidenceTotal() <= 0) {
            return 0.0;
        }
        List<Integer> hits = new ArrayList<>(item.evidenceRanks());
        hits.sort(Integer::compareTo);
        double sum = 0.0;
        int counted = Math.min(hits.size(), item.evidenceTotal());
        for (int index = 0; index < counted; index++) {
            sum += (index + 1) / (double) hits.get(index);
        }
        return sum / item.evidenceTotal();
    }

    /** 找回的金标数 / 要求的金标数。 */
    public static double evidenceCoverage(EvalRunItem item) {
        if (item.evidenceTotal() <= 0) {
            return 0.0;
        }
        return Math.min(1.0, (double) item.evidenceMatched() / item.evidenceTotal());
    }

    /** 把一路的成绩套回与融合结果同一套口径（通道与整体同尺）。 */
    public static EvalRunItem asChannel(EvalRunItem item, ChannelScore channel) {
        List<Integer> ranks = channel.ranks();
        return new EvalRunItem(
                item.testsetItemId(),
                item.query(),
                ranks.isEmpty() ? null : ranks.get(0),
                item.latencyMs(),
                item.evidenceTotal(),
                ranks.size(),
                ranks,
                List.of());
    }

    private static List<Integer> sortedRanks(Map<String, Integer> ranks) {
        List<Integer> sorted = new ArrayList<>(ranks.values());
        sorted.sort(Comparator.naturalOrder());
        return sorted;
    }
}
