package com.recalldesk.domain.eval;

import java.time.Instant;

/** 逐题任务发件箱的一行。 */
public record EvalRunTask(
        /** 任务 id。 */
        String id,
        /** 属于哪次 run。 */
        String runId,
        /** 跑哪道题。 */
        String itemId,
        /** 投递/执行状态。 */
        EvalTaskStatus status,
        /** 已尝试次数。 */
        int attempts,
        /** 上一次失败原因。 */
        String lastError,
        /** 创建时间。 */
        Instant createdAt,
        /** 投递到队列的时间；还没投为 null。 */
        Instant queuedAt) {
}
