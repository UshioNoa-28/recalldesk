package com.recalldesk.domain.eval;

import java.util.List;

/** 一路召回在本题上的成绩。 */
public record ChannelScore(
        /** 通道名：dense_original / dense_variant / sparse / union。 */
        String kind,
        /** 这一路用的查询文本；union 是跨路并集，没有文本，为 null。 */
        String text,
        /** 这一路命中的金标块各自排第几（升序）。 */
        List<Integer> ranks,
        /** 这一路自己的耗时（毫秒）；union 不是真实检索，为 null。 */
        Long tookMs) {
}
