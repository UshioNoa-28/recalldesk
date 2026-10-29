package com.recalldesk.domain.retrieval;

/**
 * 检索链的一条命中；dense / sparse 两路统一形状。
 *
 * score 的语义随路而变（余弦相似度 / BM25 分），融合前只用于路内排序，跨路比较没有意义
 * ——这正是 RRF 只看名次的理由；融合或重排之后 score 换成融合分/重排分，形状不变。
 * (documentId, chunkIndex) 坐标就是命中身份，不另存合并键。
 */
public record ChunkHit(
        String documentId, String documentName, int chunkIndex, Integer chunkCount, String text, double score) {}
