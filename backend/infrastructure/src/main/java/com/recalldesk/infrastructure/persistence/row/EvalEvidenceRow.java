package com.recalldesk.infrastructure.persistence.row;

import com.recalldesk.domain.eval.EvidenceQuote;
import lombok.Data;

/**
 * eval_testset_item_evidence 表的一行：一个金标 chunk。
 *
 * 没有原文片段列——用户指定的就是块号，系统不做文本匹配。
 */
@Data
public class EvalEvidenceRow {

    private String id;
    private String itemId;
    private String documentId;
    private Integer chunkIndex;
    private Integer ordinal;

    /** 领域对象 → 行。 */
    public static EvalEvidenceRow from(EvidenceQuote quote) {
        EvalEvidenceRow row = new EvalEvidenceRow();
        row.setId(quote.id());
        row.setItemId(quote.itemId());
        row.setDocumentId(quote.documentId());
        row.setChunkIndex(quote.chunkIndex());
        row.setOrdinal(quote.ordinal());
        return row;
    }

    public EvidenceQuote toDomain() {
        return new EvidenceQuote(
                id, itemId, documentId, chunkIndex == null ? 0 : chunkIndex, ordinal == null ? 0 : ordinal);
    }
}
