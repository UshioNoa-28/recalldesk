package com.recalldesk.domain.eval;

import java.util.List;

/** 一道题：问句 + 它的金标块。 */
public record EvalTestSetItem(
        /** 题目 id。 */
        String id,
        /** 问句。 */
        String query,
        /** 金标块；每个都是一个必中目标。 */
        List<EvidenceQuote> evidence) {

    public EvalTestSetItem {
        evidence = List.copyOf(evidence);
    }
}
