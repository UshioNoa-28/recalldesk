package com.recalldesk.domain.eval;

import java.util.List;

/** 一道题在一次 run 里的原始结果。 */
public record EvalRunItem(
        /** 这道题的 id（指向 eval_testset_items）。 */
        String testsetItemId,
        /** 题面；从题目表联查带出，结果表不存副本。 */
        String query,
        /** 最早命中的金标块排第几（1 起）；一块没捞到时为 null。 */
        Integer hitRank,
        /** 本次检索耗时（毫秒）。 */
        double latencyMs,
        /** 这题要求命中几个金标块。 */
        int evidenceTotal,
        /** 前 k 名里实际命中几个金标块。 */
        int evidenceMatched,
        /** 命中的金标块各自排第几（升序）；一块没命中时为空列表。 */
        List<Integer> evidenceRanks,
        /** 融合前每一路的成绩；没有轨迹时为空列表。 */
        List<ChannelScore> channels) {

    public EvalRunItem {
        evidenceRanks = evidenceRanks == null ? List.of() : List.copyOf(evidenceRanks);
        channels = channels == null ? List.of() : List.copyOf(channels);
    }
}
