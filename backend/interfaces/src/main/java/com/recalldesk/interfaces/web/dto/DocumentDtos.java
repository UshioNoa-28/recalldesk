package com.recalldesk.interfaces.web.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.recalldesk.domain.retrieval.ChannelTrace;
import com.recalldesk.domain.retrieval.ChunkHit;
import com.recalldesk.domain.retrieval.ChunkRecord;
import java.util.List;

/**
 * 文档路由的出参形状（键序 = record 分量顺序）：
 * 键序 = record 分量顺序（Jackson 按声明序序列化），null 照旧输出。
 */
public final class DocumentDtos {

    private DocumentDtos() {}

    /** 列表项与详情共用的文档视图。 */
    public record DocumentView(
            String id,
            String name,
            String status,
            Integer chunkCount,
            String createdAt,
            String indexedAt,
            String errorMessage) {}

    /** POST /documents 与 POST /documents/{id}/reindex 的返回。 */
    public record DocumentCreated(String documentId, String name, String status) {}

    /** GET /documents。 */
    public record DocumentList(List<DocumentView> items, long total, int page, int pageSize) {}

    /** GET /documents/{id}/chunks。 */
    public record DocumentChunks(String documentId, int totalChunks, List<ChunkRecord> chunks) {}

    /**
     * GET /search。
     *
     * channels 只在 {@code channels=true} 时出现（条件加键，
     * 不是给 null），所以这一层单独关掉 null 输出。
     */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public record SearchResult(String query, List<ChunkHit> hits, List<ChannelTrace> channels) {}

    /**
     * DELETE /documents/{id}。
     *
     * removedEvalItems 是这次删除连带清掉的评测题数（引用了这篇文档的题）。
     * 静默清库，调用方事后才发现评测集少了题；这里把数目摆到响应里。
     */
    public record DocumentDeleted(String documentId, boolean deleted, int removedEvalItems) {}
}
