package com.recalldesk.application.eval.dto;

import java.util.List;

/** 上传时一行解析出来的题。 */
public record ImportedQuestion(
        /** 问句。 */
        String query,
        /** 金标块。 */
        List<ImportedChunk> chunks) {

    public ImportedQuestion {
        chunks = List.copyOf(chunks);
    }

    /** 一个金标：文档 + 块号。 */
    public record ImportedChunk(
            /** 出处文档 id。 */
            String documentId,
            /** 出处文档里的块号（0 起）。 */
            int chunkIndex) {}
}
