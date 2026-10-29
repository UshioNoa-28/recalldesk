package com.recalldesk.application.worker;

import com.recalldesk.application.document.DocumentTextExtractor;
import com.recalldesk.application.document.IndexingService;
import com.recalldesk.domain.documents.Document;
import com.recalldesk.domain.documents.DocumentTask;
import com.recalldesk.domain.port.persistence.DocumentFileStorage;
import com.recalldesk.domain.port.persistence.DocumentRepository;
import com.recalldesk.domain.port.persistence.DocumentTaskRepository;
import com.recalldesk.domain.port.queue.DocumentTaskQueue;
import com.recalldesk.domain.port.ops.UnitOfWork;
import com.recalldesk.domain.task.TaskFields;
import com.recalldesk.domain.task.TaskPolicy;
import java.time.Instant;
import java.util.Map;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import com.recalldesk.domain.exception.indexing.EmptyContentException;

/**
 * 任务消费者：从队列消费文档索引任务，建向量并回写状态。
 *
 * 设计说明（消费循环 / ACK 规则见 {@link BaseConsumer}）：
 * - 只依赖 DocumentTaskQueue 接口，不碰 Redis 细节；
 * - 任务只有一种：给一篇文档建向量；删除是请求内同步完成的确定性操作，不经过队列；
 * - 事务只包住写库：读文档、读原件、切块、embedding 都在事务外，慢 I/O 不占数据库连接；
 *   索引块先落库、任务与文档状态后落库，两步之间崩溃时任务仍是 PENDING，重投后
 *   整篇替换幂等重来；
 * - 业务失败的重试靠 task 回 PENDING（指数退避），由 DocumentTaskPublisher 重新
 *   投递，避免毒丸消息阻塞队列。
 */
public class DocumentTaskConsumer extends BaseConsumer {

    private static final Logger log = LoggerFactory.getLogger(DocumentTaskConsumer.class);

    /** 消费者名前缀（容器编排排查用得到具体名）。 */
    private static final String CONSUMER_NAME_PREFIX = "consumer";

    private final DocumentRepository documents;
    private final DocumentTaskRepository outbox;
    private final DocumentFileStorage fileStorage;
    private final IndexingService indexingService;

    public DocumentTaskConsumer(
            DocumentTaskQueue queue,
            UnitOfWork unitOfWork,
            TaskPolicy policy,
            DocumentRepository documents,
            DocumentTaskRepository outbox,
            DocumentFileStorage fileStorage,
            IndexingService indexingService) {
        this(queue, unitOfWork, policy, documents, outbox, fileStorage, indexingService, null);
    }

    public DocumentTaskConsumer(
            DocumentTaskQueue queue,
            UnitOfWork unitOfWork,
            TaskPolicy policy,
            DocumentRepository documents,
            DocumentTaskRepository outbox,
            DocumentFileStorage fileStorage,
            IndexingService indexingService,
            String consumerName) {
        super(queue, unitOfWork, policy, CONSUMER_NAME_PREFIX, consumerName);
        this.documents = documents;
        this.outbox = outbox;
        this.fileStorage = fileStorage;
        this.indexingService = indexingService;
    }

    @Override
    protected Map<String, String> extractTaskIds(Map<String, String> fields) {
        String taskId = fields.get("task_id");
        String documentId = fields.get("document_id");
        if (TaskFields.missing(taskId) || TaskFields.missing(documentId)) {
            return null;
        }
        return fields("task_id", taskId, "document_id", documentId);
    }

    /**
     * 执行索引任务：读原件 → 切块/embedding（事务外）→ 落块 → 回写任务与文档状态。
     *
     * 业务失败在本方法内落库并正常返回（由调用方 ACK）；只有提交失败才会抛出。
     * 失败时：attempts+1、task 回 PENDING（指数退避，等 DocumentTaskPublisher 重新投递）；
     * 超限则 task 和 document 都标 FAILED。
     */
    @Override
    protected void handleTask(Map<String, String> ids) {
        String taskId = ids.get("task_id");
        String documentId = ids.get("document_id");

        Optional<Document> found = documents.get(documentId);
        if (found.isEmpty()) {
            // 文档已不存在，任务直接算成功（幂等）
            unitOfWork().execute(() -> outbox.markSuccess(taskId));
            return;
        }
        Document document = found.get();

        int chunkCount;
        try {
            byte[] content = fileStorage.read(document.storageKey());
            String text = DocumentTextExtractor.extract(content);
            // 切块与 embedding 放在事务外
            chunkCount = indexingService.ingest(
                    document.id(), document.userId(), document.name(), text);
        } catch (RuntimeException exc) {
            recordFailure(taskId, document, exc);
            return;
        }

        // 块已落库；这里再提交任务与文档状态。两步之间崩溃时重投，整篇替换幂等
        unitOfWork().execute(() -> {
            outbox.markSuccess(taskId);
            documents.update(document.markIndexed(chunkCount, Instant.now()));
        });
    }

    private void recordFailure(String taskId, Document document, RuntimeException exc) {
        String error = TaskErrors.describe(exc);
        if (exc instanceof EmptyContentException) {
            // 切不出分块是内容本身的问题，重试不会变好：直接终态，
            // 不进指数退避（否则这类文档要白跑满 10 次重试才 FAILED）
            unitOfWork().execute(() -> {
                outbox.markFailed(taskId);
                documents.update(document.markFailed(error));
            });
            log.error("内容切不出分块，任务直接终态失败: task={} doc={}", taskId, document.id());
            return;
        }
        unitOfWork().execute(() -> {
            outbox.recordFailure(taskId, error);
            Optional<DocumentTask> entry = outbox.get(taskId);
            if (entry.isPresent() && entry.get().attempts() >= policy().maxAttempts()) {
                outbox.markFailed(taskId);
                documents.update(document.markFailed(error));
                log.error("任务失败达到上限: task={} doc={} error={}", taskId, document.id(), error);
            } else {
                // 带上第几次失败：重试次数是可观测事实，只报「未超限」等于让排障的人去翻库
                log.warn("任务失败（未超限，回 PENDING 等重投）: task={} doc={} attempts={} error={}",
                        taskId, document.id(), entry.map(DocumentTask::attempts).orElse(-1), error);
            }
        });
    }
}
