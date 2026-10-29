package com.recalldesk.domain.eval;

import com.recalldesk.domain.retrieval.FusionConfig;

/** 一次 run 的检索配方，落 eval_runs.config。 */
public record EvalRunConfig(
        /** 这次取前几块；也是 recall@k 里的 k。 */
        int topK,
        /** 本次是否走 LLM 查询改写。 */
        boolean queryRewrite,
        /** 本次是否走重排。 */
        boolean rerank,
        /** 融合配方；null 表示用装配默认（RRF, k=60）。 */
        FusionConfig fusion) {
}
