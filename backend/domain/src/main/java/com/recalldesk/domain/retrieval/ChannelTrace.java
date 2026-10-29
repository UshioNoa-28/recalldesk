package com.recalldesk.domain.retrieval;

import java.util.Comparator;
import java.util.List;

/**
 * 一路召回的现场快照（融合前、rerank 前）：查询文本 + 本路命中列表 + 这一路花了多久。
 *
 * kind 是节点评估的分组键：dense_original / dense_variant / sparse。
 * 命中在本路里的名次以排序后的列表位置为准。
 *
 * tookMs 只到「这一路」为止：embed 与查库都算在内，融合与重排不算。消融归因问的是
 * 「把改写路关掉能省多少时间」，那个答案只能在路还各自跑的时候记下来，事后拆不回来。
 */
public record ChannelTrace(String kind, String text, List<ChunkHit> hits, long tookMs) {

    /**
     * 定格一路：入库前按本路 score 降序排好——存储侧永远满足名次约定。
     *
     * 各路返回的列表本来就该有序，但检索端口的契约没承诺过，这里自己兜底。
     */
    public static ChannelTrace of(String kind, String text, List<ChunkHit> hits, long tookMs) {
        List<ChunkHit> sorted = hits.stream()
                .sorted(Comparator.comparingDouble(ChunkHit::score).reversed())
                .toList();
        return new ChannelTrace(kind, text, sorted, tookMs);
    }
}
