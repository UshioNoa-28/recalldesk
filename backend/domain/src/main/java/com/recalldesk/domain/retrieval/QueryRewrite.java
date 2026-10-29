package com.recalldesk.domain.retrieval;

import java.util.List;

/**
 * 查询改写的产出：dense 用的语义变体若干 + sparse 用的关键词一组。
 *
 * queries 缺省或为空即视为坏输出：抛 IllegalArgumentException，让适配器把上游的
 * 坏响应变成显式失败，不静默退化。
 *
 * @param queries 语义多样的检索改写变体（非空）
 * @param keywords BM25 高信号关键词（可空——空时稀疏路退回用 queries 的第一条）
 */
public record QueryRewrite(List<String> queries, List<String> keywords) {

    public QueryRewrite {
        if (queries == null || queries.isEmpty()) {
            throw new IllegalArgumentException("queries 至少要有 1 条，收到 " + queries);
        }
        keywords = keywords == null ? List.of() : List.copyOf(keywords);
        queries = List.copyOf(queries);
    }

    /** 稀疏通道（BM25）实际使用的查询文本。 */
    public String sparseText() {
        return keywords.isEmpty() ? queries.get(0) : String.join(" ", keywords);
    }
}
