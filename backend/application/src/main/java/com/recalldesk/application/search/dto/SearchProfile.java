package com.recalldesk.application.search.dto;

import com.recalldesk.application.search.FusionSpec;

/** 一次检索的档位：这几路各开不开、融合怎么合。 */
public record SearchProfile(
        /** 是否走 LLM 查询改写（没配 LLM 时这一路自动缺省）。 */
        boolean rewrite,
        /** 是否走重排（网关门没报重排可用时这一路自动缺省）。 */
        boolean rerank,
        /** 融合档位；null 表示用装配默认。 */
        FusionSpec fusion) {

    /** 两路全开、融合走装配默认。 */
    public static SearchProfile defaults() {
        return new SearchProfile(true, true, null);
    }
}
