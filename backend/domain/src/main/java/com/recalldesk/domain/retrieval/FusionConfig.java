package com.recalldesk.domain.retrieval;

import java.util.Map;

/** 融合配方的持久化形状（存在 eval_runs.config 里）。 */
public record FusionConfig(
        /** rrf 或 weighted；null 表示没指定。 */
        String method,
        /** RRF 分母常数；null 表示没指定。 */
        Integer rrfK,
        /** minmax 或 zscore；null 表示没指定。 */
        String norm,
        /** 按组权重（dense / sparse）；null 或空表示没指定。 */
        Map<String, Double> weights) {
}
