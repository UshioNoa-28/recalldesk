package com.recalldesk.application.search;

import static org.assertj.core.api.Assertions.assertThat;

import com.recalldesk.domain.retrieval.ChannelTrace;
import com.recalldesk.domain.retrieval.ChunkHit;
import com.recalldesk.application.search.FusionSpec;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 融合的数值对齐测试。
 *
 * 每一条预期值都不是手算的，而是照着参考实现的实跑结果抄下来的
 * （用例与 tests/test_search_service.py 里的 RrfFuseTests / WeightedFuseTests /
 * ZScoreNormTests 一一对应）——这一档的存在理由就是"同配方走同一条路"，
 * 拿它跟自己的算术对表等于什么都没测。
 */
class FusionTest {

    private static final Map<String, Double> EQUAL = Map.of("dense", 1.0, "sparse", 1.0);

    private static ChunkHit hit(int chunkIndex, double score) {
        return new ChunkHit("doc-1", "a.txt", chunkIndex, 3, "内容", score);
    }

    private static ChannelTrace trace(String kind, String text, ChunkHit... hits) {
        // 融合只看名次与分数，耗时这一路在本测试里无关心，填 0 占位
        return ChannelTrace.of(kind, text, List.of(hits), 0);
    }

    private static FusionSpec rrf(int rrfK) {
        return new FusionSpec("rrf", rrfK, "minmax", EQUAL);
    }

    private static FusionSpec weighted(String norm, Map<String, Double> weights) {
        return new FusionSpec("weighted", 60, norm, weights);
    }

    /**
     * 融合分不截断（出参就是 double 原值），但测试期望值写成四位小数便于人读，
     * 所以把实测值也按四位比较——差的是展示精度，不是口径。
     */
    private static void assertFused(List<ChunkHit> fused, List<Integer> order, List<Double> scores) {
        assertThat(fused).extracting(ChunkHit::chunkIndex).isEqualTo(order);
        assertThat(fused.stream().map(hit -> round4(hit.score())).toList())
                .isEqualTo(scores);
    }

    /** 四位小数的展示精度：只用于断言，不是生产口径。 */
    private static double round4(double value) {
        return Math.round(value * 10_000d) / 10_000d;
    }

    /** 两路名次集合一样（0/1 各占一个第一），但分差形状不同：dense 里 0 领先一大截。 */
    private static List<ChannelTrace> twoChannels() {
        return List.of(
                trace("dense_original", "q", hit(0, 0.95), hit(1, 0.30), hit(2, 0.29)),
                trace("sparse", "q", hit(1, 20.0), hit(0, 19.9), hit(2, 0.1)));
    }

    @Test
    @DisplayName("RRF：两路对称时同分，名次并列按首见顺序")
    void rrfFusesByRankOnly() {
        List<ChunkHit> fused = Fusion.rrf(
                List.of(List.of(hit(0, 0.9), hit(1, 0.5)), List.of(hit(1, 12.0), hit(0, 3.0))), 2, 2);

        // 块 0：1/(2+0) + 1/(2+1)；块 1：1/(2+1) + 1/(2+0) —— 同一个数
        assertFused(fused, List.of(0, 1), List.of(0.8333, 0.8333));
    }

    @Test
    @DisplayName("RRF：只出现在一路的 chunk 只累加那一路的贡献")
    void rrfKeepsSingleChannelContributions() {
        List<ChunkHit> fused = Fusion.rrf(List.of(List.of(hit(0, 0.9)), List.of(hit(2, 5.0))), 2, 5);

        // 各自都是本路第一：1/(2+0) = 0.5
        assertFused(fused, List.of(0, 2), List.of(0.5, 0.5));
    }

    @Test
    @DisplayName("RRF：截断到 top_k，空路不产生候选")
    void rrfTruncates() {
        List<ChunkHit> dense = new java.util.ArrayList<>();
        for (int i = 0; i < 5; i++) {
            dense.add(hit(i, 1.0 - i * 0.1));
        }

        List<ChunkHit> fused = Fusion.rrf(List.of(dense, List.of()), 2, 2);

        assertFused(fused, List.of(0, 1), List.of(0.5, 0.3333));
    }

    @Test
    @DisplayName("同一份轨迹：RRF 看到的并列，加权记住了分差")
    void scoreGapsChangeTheOrderWhereRrfSeesATie() {
        List<ChannelTrace> traces = twoChannels();

        assertFused(Fusion.fuse(traces, rrf(2), 3), List.of(0, 1, 2), List.of(0.8333, 0.8333, 0.5));
        assertFused(
                Fusion.fuse(traces, weighted("minmax", EQUAL), 3),
                List.of(0, 1, 2),
                List.of(1.995, 1.0152, 0.0));
    }

    @Test
    @DisplayName("组权重压过单路：sparse 拿到 5.0 时它在榜首的块 1 反超 dense 的块 0")
    void groupWeightDominatesASingleChannel() {
        // 注意：weights={"sparse": 5.0} 是整体替换，dense 缺席即权重 0，这条期望值就是这么来的
        List<ChunkHit> fused = Fusion.fuse(
                twoChannels(), weighted("minmax", Map.of("sparse", 5.0)), 3);

        assertFused(fused, List.of(1, 0, 2), List.of(5.0, 4.9749, 0.0));
    }

    @Test
    @DisplayName("组内平摊：改写变体的数量不改变 dense 与 sparse 的相对话语权")
    void rewriteVariantsShareTheDenseWeight() {
        // 块 0 是两条 dense 的第一（各拿 1.0/2），块 1 是唯一的 sparse 第一（1.0）
        List<ChannelTrace> traces = List.of(
                trace("dense_original", "q", hit(0, 0.9)),
                trace("dense_variant", "q2", hit(0, 0.8)),
                trace("sparse", "kw", hit(1, 12.0)));

        assertFused(
                Fusion.fuse(traces, weighted("minmax", EQUAL), 2), List.of(0, 1), List.of(1.0, 1.0));
    }

    @Test
    @DisplayName("单条命中的路给满分而不是 0：否则这一路会被静默丢掉")
    void singletonChannelGetsFullMarksNotZero() {
        List<ChannelTrace> traces = List.of(
                trace("sparse", "q", hit(7, 0.123)),
                trace("dense_original", "q", hit(0, 0.9), hit(1, 0.5)));

        List<ChunkHit> fused = Fusion.fuse(traces, weighted("minmax", EQUAL), 3);

        assertFused(fused, List.of(0, 7, 1), List.of(1.0, 1.0, 0.0));
        // minmax 把每路的尾名钉在 0
        assertThat(fused.get(2).score()).isEqualTo(0.0);
    }

    @Test
    @DisplayName("缺席的组不贡献也不重新归一：缩放常数没有意义")
    void absentGroupIsNotRenormalized() {
        List<ChannelTrace> traces = List.of(trace("sparse", "kw", hit(3, 30.0), hit(4, 20.0), hit(5, 10.0)));

        assertFused(
                Fusion.fuse(traces, weighted("minmax", Map.of("sparse", 2.0)), 3),
                List.of(3, 4, 5),
                List.of(2.0, 1.0, 0.0));
    }

    @Test
    @DisplayName("并列按坐标破：同配方两次 run 的名次不许抖")
    void tiesBrokenByCoordinate() {
        List<ChannelTrace> traces = List.of(
                trace("sparse", "kw", hit(1, 5.0)),
                trace("dense_original", "q", hit(0, 0.9)));

        assertFused(
                Fusion.fuse(traces, weighted("minmax", EQUAL), 2), List.of(0, 1), List.of(1.0, 1.0));
    }

    @Test
    @DisplayName("空轨迹融合出空列表")
    void emptyTracesFuseToEmpty() {
        assertThat(Fusion.fuse(List.of(), weighted("minmax", EQUAL), 3)).isEmpty();
    }

    @Test
    @DisplayName("zscore 不抹平 minmax 抹平的那两端：头名不足 1，尾名给到负分")
    void zscoreKeepsTheTailThatMinmaxFlattens() {
        List<ChannelTrace> traces = List.of(trace("sparse", "kw", hit(0, 10.0), hit(1, 9.0), hit(2, 1.0)));

        assertFused(
                Fusion.fuse(traces, weighted("minmax", EQUAL), 3),
                List.of(0, 1, 2),
                List.of(1.0, 0.8889, 0.0));
        assertFused(
                Fusion.fuse(traces, weighted("zscore", EQUAL), 3),
                List.of(0, 1, 2),
                List.of(0.9138, 0.7897, -0.2035));
    }

    @Test
    @DisplayName("全同分退化给满分（zscore 的除零会被 epsilon 拦住）")
    void constantScoresDegradeToFullMarks() {
        List<ChannelTrace> traces = List.of(trace("sparse", "kw", hit(0, 5.0), hit(1, 5.0)));

        assertFused(Fusion.fuse(traces, weighted("zscore", EQUAL), 2), List.of(0, 1), List.of(1.0, 1.0));
    }
}
