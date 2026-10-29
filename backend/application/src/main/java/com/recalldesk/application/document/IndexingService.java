package com.recalldesk.application.document;

import com.recalldesk.domain.port.model.EmbeddingClient;
import com.recalldesk.domain.port.model.TextSplitter;
import com.recalldesk.domain.port.ops.UnitOfWork;
import com.recalldesk.domain.port.persistence.ChunkIndex;
import java.util.List;
import org.springframework.stereotype.Component;
import com.recalldesk.domain.exception.indexing.EmptyContentException;

/**
 * 索引编排：切块 → embedding → 整篇写入检索索引。
 *
 * 切块与 embedding 在事务外完成（那是慢 I/O，不该占着数据库连接）；只有
 * 「删旧块 + 写新块」进工作单元，插入失败时旧块还在。
 *
 * 切不出块就是内容本身的问题，重试多少次都不会变好——抛出去让消费侧把文档标 failed，
 * 而不是"写成功 0 块"那种看起来没事的静默。
 */
@Component
public class IndexingService {

    private final ChunkIndex index;
    private final EmbeddingClient embeddingClient;
    private final TextSplitter textSplitter;
    private final UnitOfWork unitOfWork;

    public IndexingService(
            ChunkIndex index, EmbeddingClient embeddingClient, TextSplitter textSplitter, UnitOfWork unitOfWork) {
        this.index = index;
        this.embeddingClient = embeddingClient;
        this.textSplitter = textSplitter;
        this.unitOfWork = unitOfWork;
    }

    /** 整篇替换一个文档的可检索块，返回写入块数。 */
    public int ingest(String documentId, String userId, String name, String text) {
        List<String> chunks = textSplitter.split(text);
        if (chunks.isEmpty()) {
            throw new EmptyContentException("文档没有可索引的内容");
        }
        List<double[]> vectors = embeddingClient.embed(chunks);
        unitOfWork.execute(() -> {
            index.deleteDocument(documentId);
            index.insertChunks(documentId, userId, name, chunks, vectors);
        });
        return chunks.size();
    }

}
