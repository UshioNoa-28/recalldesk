package com.recalldesk.domain.eval;

import java.time.Instant;

/** 一个评测集。 */
public record EvalTestSet(
        /** 评测集 id。 */
        String id,
        /** 归属用户。 */
        String userId,
        /** 集名。 */
        String name,
        /** 里面的题目数；由题目表数出来，不是本表的列。 */
        int itemCount,
        /** 创建时间。 */
        Instant createdAt) {
}
