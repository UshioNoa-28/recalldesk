package com.recalldesk.domain.eval;

import java.time.Instant;
import java.util.Map;

/** 一次评测运行。 */
public record EvalRun(
        /** run id。 */
        String id,
        /** 归属用户；逐题 worker 靠它拿到该用谁的检索视野。 */
        String userId,
        /** 跑的是哪个评测集。 */
        String testsetId,
        /** 生命周期状态。 */
        EvalRunStatus status,
        /** 当时的检索配方快照。 */
        EvalRunConfig config,
        /** 聚合好的指标（recall@k / map@k / evidence_coverage / queries / avg_latency_ms / buckets / channels）。 */
        Map<String, Object> metrics,
        /** 失败原因；正常结束为 null。 */
        String errorMessage,
        /** 创建时间。 */
        Instant createdAt,
        /** 结束时间；还在跑为 null。 */
        Instant finishedAt,
        /** 已落定的题数；由逐题结果数出来。 */
        int progressDone,
        /** 本次要跑的题数。 */
        int progressTotal) {
}
