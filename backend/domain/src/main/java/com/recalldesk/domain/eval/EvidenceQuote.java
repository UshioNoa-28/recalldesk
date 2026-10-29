package com.recalldesk.domain.eval;

/** 一个金标：某个文档的第几块。 */
public record EvidenceQuote(
        /** 金标行 id。 */
        String id,
        /** 所属题目 id。 */
        String itemId,
        /** 出处文档 id。 */
        String documentId,
        /** 出处文档里的块号（0 起）。 */
        int chunkIndex,
        /** 在本题证据列表里的顺序。 */
        int ordinal) {

    /** 这条命中是否就是本金标：同文档且块号相同。 */
    public boolean matches(String hitDocumentId, int hitChunkIndex) {
        return documentId.equals(hitDocumentId) && chunkIndex == hitChunkIndex;
    }
}
