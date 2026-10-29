package com.recalldesk.application.document;

import com.recalldesk.application.document.dto.DocumentContent;
import com.recalldesk.domain.exception.indexing.EmptyContentException;
import com.recalldesk.application.search.dto.SearchOutcome;
import com.recalldesk.application.search.SearchService;
import com.recalldesk.domain.Page;
import com.recalldesk.domain.documents.Document;
import com.recalldesk.domain.documents.DocumentStatus;
import com.recalldesk.domain.exception.documents.DocumentNotFoundException;
import com.recalldesk.domain.port.model.TextSplitter;
import com.recalldesk.domain.port.ops.UnitOfWork;
import com.recalldesk.domain.port.persistence.ChunkIndex;
import com.recalldesk.domain.port.persistence.DocumentFileStorage;
import com.recalldesk.domain.port.persistence.DocumentRepository;
import com.recalldesk.domain.port.persistence.DocumentTaskRepository;
import com.recalldesk.domain.port.persistence.EvalRepository;
import com.recalldesk.domain.port.persistence.EvalRunRepository;
import com.recalldesk.domain.retrieval.ChunkRecord;
import com.recalldesk.application.search.dto.SearchProfile;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * 文档用例编排：上传、列表、详情、分块、原文、检索、重索引、删除。
 *
 * 上传时先校验"文本读得出来、也切得出块"，然后存本地文件 →
 * 一个事务写 documents + document_tasks → 返回 PENDING。索引交给后台
 * publisher/consumer，入口把内容性问题挡掉，worker 就不用为它们空跑退避。
 */
public class DocumentService {

    private static final Logger log = LoggerFactory.getLogger(DocumentService.class);

    private final DocumentRepository repository;
    private final DocumentFileStorage fileStorage;
    private final DocumentTaskRepository outbox;
    private final EvalRepository evalRepository;
    private final EvalRunRepository evalRuns;
    private final ChunkIndex chunkIndex;
    private final TextSplitter textSplitter;
    private final SearchService searchService;
    private final UnitOfWork unitOfWork;

    public DocumentService(
            DocumentRepository repository,
            DocumentFileStorage fileStorage,
            DocumentTaskRepository outbox,
            EvalRepository evalRepository,
            EvalRunRepository evalRuns,
            ChunkIndex chunkIndex,
            TextSplitter textSplitter,
            SearchService searchService,
            UnitOfWork unitOfWork) {
        this.repository = repository;
        this.fileStorage = fileStorage;
        this.outbox = outbox;
        this.evalRepository = evalRepository;
        this.evalRuns = evalRuns;
        this.chunkIndex = chunkIndex;
        this.textSplitter = textSplitter;
        this.searchService = searchService;
        this.unitOfWork = unitOfWork;
    }

    /** 保存原件 + 写文档与任务，返回 PENDING 文档；name 就是上传时的文件名。 */
    public Document ingest(String name, byte[] content, String mediaType, String userId) {
        validateIndexable(content);

        String documentId = UUID.randomUUID().toString();
        String storageKey = fileStorage.save(documentId, content);
        Document document = new Document(
                documentId,
                userId,
                name,
                storageKey,
                content.length,
                mediaType,
                DocumentStatus.PENDING,
                null,
                null,
                Instant.now(),
                null);

        try {
            unitOfWork.execute(() -> {
                repository.add(document);
                // 任务与文档同事务提交：要么都有，要么都回滚
                outbox.add(document.id());
            });
        } catch (RuntimeException exc) {
            // 补偿：数据库失败时把已保存的本地文件删掉，避免孤儿文件
            deleteFileBestEffort(storageKey);
            throw exc;
        }
        return document;
    }

    /**
     * 归属范围内的文档行：不是该用户的文档与文档不存在给出同一个错——
     * 403 会告诉对方「这个 id 是别人的」，等于把 id 空间变成了可探测的资源清单。
     */
    public Document get(String userId, String documentId) {
        return repository.getOwned(userId, documentId).orElseThrow(() -> new DocumentNotFoundException(documentId));
    }

    public Page<Document> list(String userId, int page, int pageSize) {
        return repository.list(userId, page, pageSize);
    }

    /** 返回完整检索产出：融合 hits + 融合前各路轨迹（消融归因要用 channels）。 */
    public SearchOutcome search(String query, Integer topK, SearchProfile profile, String userId) {
        return searchService.search(query, topK, profile, userId);
    }

    /** 列出文档的全部分块（以索引库为准）；文档不存在或不属于本人时先 404。 */
    public List<ChunkRecord> chunks(String userId, String documentId) {
        get(userId, documentId);
        return chunkIndex.getDocumentChunks(documentId);
    }

    /** 读取原始文档文本（文档名, 文本）——磁盘上的原件才是权威，不是 chunks 里的副本。 */
    public DocumentContent content(String userId, String documentId) {
        Document document = get(userId, documentId);
        return new DocumentContent(
                document.name(), DocumentTextExtractor.extract(fileStorage.read(document.storageKey())));
    }

    /**
     * 重新索引：FAILED 修好依赖后救回来，SUCCESS 换分块/嵌入参数后重建。
     *
     * 一个事务里重置文档状态 + 写 index 任务，之后与首次索引走完全相同的路
     * （publisher 投递 → consumer 建向量）。PENDING（正在处理）拒绝，免得手滑叠任务；
     * 底层 upsert 先清旧块再写新块，重复任务本身也无害。
     */
    public Document reindex(String userId, String documentId) {
        Document document = get(userId, documentId);
        if (document.status() == DocumentStatus.PENDING) {
            throw new IllegalArgumentException("文档正在处理中，完成或失败后再重新索引");
        }
        Document reset = document.resetForReindex();
        unitOfWork.execute(() -> {
            repository.update(reset);
            outbox.add(documentId);
        });
        return reset;
    }

    /**
     * 删除文档：一个事务（删受影响的 run + 清引用题 + documents 行）→ 原始文件 best-effort。
     *
     * 删除是确定性操作，同步做完：chunks 由 doc_id 外键级联，document_tasks 随文档行级联；
     * 引用它的题目和基于这些题目的 run 一并删——run 的指标分母是题集当前题数，
     * 留下一条题被删的 run 只会得到对不上的历史。
     *
     * @return 连带删掉的评测题数：调用方该知道自己删的这篇文档被几道题引用——
     *     静默清掉别人攒好的评测集是最难查的那种数据丢失。
     */
    public int delete(String userId, String documentId) {
        Document document = get(userId, documentId);
        int removedItems = unitOfWork.executeFor(() -> {
            int removedRuns = evalRuns.deleteRunsReferencingDocument(documentId);
            int removed = evalRepository.deleteItemsReferencingDocument(documentId);
            repository.delete(userId, documentId);
            if (removedRuns > 0) {
                log.info("删文档连带删除评测 run: doc={} runs={}", documentId, removedRuns);
            }
            return removed;
        });
        if (removedItems > 0) {
            log.info("删文档连带删除引用它的评测题: doc={} items={}", documentId, removedItems);
        }
        deleteFileBestEffort(document.storageKey());
        return removedItems;
    }

    /** 文本读不出来或切不出块，就是这篇文档本身的问题——当场拒，不派 worker 空跑退避。 */
    private void validateIndexable(byte[] content) {
        String text = DocumentTextExtractor.extract(content);
        if (textSplitter.split(text).isEmpty()) {
            throw new EmptyContentException("文档内容切不出任何分块，无法索引");
        }
    }

    private void deleteFileBestEffort(String storageKey) {
        try {
            fileStorage.delete(storageKey);
        } catch (RuntimeException exc) {
            // 补偿失败只记日志，不影响主流程：文件是本地盘上的孤儿，
            // 静默吞掉反而会让磁盘无声涨起来
            log.warn("补偿删除文件失败（孤儿文件留在磁盘上）: key={}", storageKey, exc);
        }
    }

}
