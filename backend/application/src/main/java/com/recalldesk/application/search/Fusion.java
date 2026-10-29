package com.recalldesk.application.search;

import com.recalldesk.domain.retrieval.ChannelTrace;
import com.recalldesk.domain.retrieval.ChunkHit;
import com.recalldesk.application.search.FusionSpec;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 多路召回的融合：RRF（只看名次）与加权归一化（用分数）两档。
 *
 * 为什么不 ports + infrastructure：融合是纯计算——进去每路的命中列表，出来一个排好序的列表，
 * 不打网络、不读库、不需要"换实现适配环境"。它需要的是<b>按 run 的配方换算法做 A/B</b>，
 * 那是档位不是依赖。哪天要上学习式融合（拟合权重要读特征、打模型），那一步才有 I/O。
 *
 * 两档的语义差别是本项目最容易被误读的一处：
 * - RRF 不需要任何跨路可比假设，代价是丢分差信息。
 * - 加权融合必须先把各路 score <b>路内</b>归一化（余弦与 BM25 两种量纲），
 *   归一化之后跨路相加才"看起来"可比。这一步是假设不是事实，见 {@link #weighted}。
 *
 * 调用方只该用 {@link #fuse}：它按 FusionSpec 分派，保证同一份配方在任何地方走出同一条路。
 */
public final class Fusion {

    private static final double EPSILON = 1e-6;

    /** 坐标即命中身份，不另存合并键；document_id 里可能出现 ':'，所以用元组而不是拼串。 */
    private record Coord(String documentId, int chunkIndex) {}

    /** 融合中的累加槽：候选本体 + 已累计的分。 */
    private record Entry(ChunkHit hit, double score) {}

    private static final Comparator<ChunkHit> BY_SCORE_DESC = Comparator.comparingDouble(ChunkHit::score).reversed();

    /** RRF 的破法：并列保持首见顺序（稳定排序），只按分数降序。 */
    private static final Comparator<Entry> BY_SCORE = Comparator.comparingDouble(Entry::score).reversed();

    /** 加权的破法：分数降序，并列按坐标升序——见 {@link #weighted}。 */
    private static final Comparator<Entry> BY_SCORE_THEN_COORD = BY_SCORE
            .thenComparing(e -> e.hit().documentId())
            .thenComparingInt(e -> e.hit().chunkIndex());

    private Fusion() {}

    /**
     * 按配方融合各路轨迹——唯一的入口，别在调用方自己挑算法。
     *
     * @param traces 各路召回轨迹（可为空）
     * @param spec   算法档位
     * @param topK   截断长度
     */
    public static List<ChunkHit> fuse(List<ChannelTrace> traces, FusionSpec spec, int topK) {
        if ("rrf".equals(spec.method())) {
            List<List<ChunkHit>> channels = new ArrayList<>(traces.size());
            for (ChannelTrace trace : traces) {
                channels.add(trace.hits());
            }
            return rrf(channels, spec.rrfK(), topK);
        }
        return weighted(traces, spec, topK);
    }

    /**
     * Reciprocal Rank Fusion：score = sum(1 / (k + rank))，rank 从 0 计。
     *
     * 每路各自按 score 降序取排名，按 (documentId, chunkIndex) 坐标合并；
     * 只出现在部分路的 chunk 只累加那些路的贡献。返回带融合分的列表（降序，截断到 topK）。
     */
    static List<ChunkHit> rrf(List<List<ChunkHit>> channels, int k, int topK) {
        Map<Coord, Entry> fused = new LinkedHashMap<>();
        for (List<ChunkHit> hits : channels) {
            List<ChunkHit> ordered = ordered(hits);
            for (int rank = 0; rank < ordered.size(); rank++) {
                accumulate(fused, ordered.get(rank), 1.0 / (k + rank));
            }
        }
        return take(rank(fused, BY_SCORE), topK);
    }

    /**
     * 路内归一化 + 按组加权求和。
     *
     * 权重按<b>组</b>给（dense / sparse），组内多条列表平摊：开改写时 dense 组是
     * "原查询 + N 个变体"，每条拿 w/n，等价于"组内取归一化分的均值"——变体数量不该
     * 改变 dense 与 sparse 的相对话语权。缺席的组不贡献也不重新归一：分数只用来排
     * 同一次查询的序，缩放常数没有意义。
     *
     * 诚实的风险说明：min-max 在截断列表上会把该路最差那条钉成 0，尾部信息被抹平；
     * BM25 长尾被压平后，sparse 的 top1 与 top3 差距可能小于 dense 的 top5 与 top6。
     * 所以这一档能不能跑赢 RRF 是要测的，不是显然的。
     */
    static List<ChunkHit> weighted(List<ChannelTrace> traces, FusionSpec spec, int topK) {
        List<ChannelTrace> live = new ArrayList<>();
        for (ChannelTrace trace : traces) {
            if (!trace.hits().isEmpty()) {
                live.add(trace);
            }
        }
        if (live.isEmpty()) {
            return List.of();
        }

        Map<String, Integer> listsPerGroup = new LinkedHashMap<>();
        for (ChannelTrace trace : live) {
            listsPerGroup.merge(FusionSpec.channelGroup(trace.kind()), 1, Integer::sum);
        }

        Map<Coord, Entry> fused = new LinkedHashMap<>();
        for (ChannelTrace trace : live) {
            String group = FusionSpec.channelGroup(trace.kind());
            double weight = spec.weights().getOrDefault(group, 0.0) / listsPerGroup.get(group);
            List<ChunkHit> hits = ordered(trace.hits());
            double[] units = normalize(hits, spec.norm());
            for (int i = 0; i < hits.size(); i++) {
                accumulate(fused, hits.get(i), weight * units[i]);
            }
        }

        // 加权后浮点相等比 RRF 常见得多，不留非确定的破法就等于让同一份配方两次 run
        // 排出不同的名次，评测数字跟着抖
        return take(rank(fused, BY_SCORE_THEN_COORD), topK);
    }

    /**
     * 本路内的名次约定：按 score 降序。
     *
     * ChannelTrace.of 入库前已经排过，但 rrf 被单测直接喂裸列表，这里再排一次是幂等的
     * （两边都是稳定排序），换来确定性。
     */
    private static List<ChunkHit> ordered(List<ChunkHit> hits) {
        List<ChunkHit> sorted = new ArrayList<>(hits);
        sorted.sort(BY_SCORE_DESC);
        return sorted;
    }

    /**
     * 一路内部的分数定标，量纲就此消失。
     *
     * minmax 把头尾钉到 1.0 / 0.0（截断列表上的最差一条必然归零，尾部信息被抹平）；
     * zscore 按均值与标准差铺开（映射 0.5 + 0.5*z），<b>不承诺落在 [0,1] 内</b>——
     * 长尾给到负分、头名不足 1，正是它相对 minmax 多留住的那点尾部区别。
     *
     * 退化情形（列表只有 1 条，或全同分）一律给 1.0：这一路"分不出高下"，给它同等满分
     * 是诚实的做法；给 0 会让这一路在加权时被静默丢掉，给 min-max 的除零结果则会污染整条链路。
     */
    private static double[] normalize(List<ChunkHit> hits, String method) {
        int size = hits.size();
        if (size < 2) {
            return ones(size);
        }
        double[] scores = new double[size];
        for (int i = 0; i < size; i++) {
            scores[i] = hits.get(i).score();
        }
        double[] out = new double[size];
        if ("zscore".equals(method)) {
            double sum = 0.0;
            for (double s : scores) {
                sum += s;
            }
            double mean = sum / size;
            double squared = 0.0;
            for (double s : scores) {
                squared += (s - mean) * (s - mean);
            }
            // Math.pow(x, 0.5) 而不是 Math.sqrt：参考实现写的是 ** 0.5，走的是 libm 的 pow
            double spread = Math.pow(squared / size, 0.5);
            if (spread <= EPSILON) {
                return ones(size);
            }
            for (int i = 0; i < size; i++) {
                out[i] = 0.5 + 0.5 * (scores[i] - mean) / spread;
            }
            return out;
        }
        double low = scores[0];
        double high = scores[0];
        for (double s : scores) {
            low = Math.min(low, s);
            high = Math.max(high, s);
        }
        double span = high - low;
        if (span <= EPSILON) {
            return ones(size);
        }
        for (int i = 0; i < size; i++) {
            out[i] = (scores[i] - low) / span;
        }
        return out;
    }

    private static double[] ones(int size) {
        double[] out = new double[size];
        Arrays.fill(out, 1.0);
        return out;
    }

    /** 累加一路的贡献：坐标第一次出现时定下候选本体，之后只加分不换人。 */
    private static void accumulate(Map<Coord, Entry> fused, ChunkHit hit, double addend) {
        Coord coord = new Coord(hit.documentId(), hit.chunkIndex());
        Entry current = fused.get(coord);
        fused.put(coord, new Entry(
                current == null ? hit : current.hit(),
                (current == null ? 0.0 : current.score()) + addend));
    }

    private static List<Entry> rank(Map<Coord, Entry> fused, Comparator<Entry> order) {
        List<Entry> ranked = new ArrayList<>(fused.values());
        ranked.sort(order);
        return ranked;
    }

    /** 融合分写回命中：形状不变，score 换成"融合后的分"，并截到 4 位小数。 */
    private static ChunkHit withScore(ChunkHit hit, double score) {
        return new ChunkHit(
                hit.documentId(), hit.documentName(), hit.chunkIndex(), hit.chunkCount(), hit.text(),
                score);
    }

    private static List<ChunkHit> take(List<Entry> ranked, int topK) {
        int limit = Math.min(topK, ranked.size());
        List<ChunkHit> out = new ArrayList<>(limit);
        for (int i = 0; i < limit; i++) {
            out.add(withScore(ranked.get(i).hit(), ranked.get(i).score()));
        }
        return List.copyOf(out);
    }
}
