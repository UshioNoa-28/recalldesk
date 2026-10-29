package com.recalldesk.domain.port.model;

import com.recalldesk.domain.retrieval.ChunkHit;
import java.util.List;

/** 把候选 chunk 按与查询的相关性重排（实现：Ollama 上的 Qwen3-Reranker 生成式重排）。 */
public interface Reranker {

    /**
     * 输入融合后的候选（含 text 等字段），返回按相关性降序的候选。
     *
     * score 会被替换成 rerank 分，其余字段原样保留；返回长度不超过 topK。
     */
    List<ChunkHit> rerank(String query, List<ChunkHit> candidates, int topK);
}
