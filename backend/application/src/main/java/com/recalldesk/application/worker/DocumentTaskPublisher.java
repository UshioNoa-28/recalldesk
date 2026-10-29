package com.recalldesk.application.worker;

import com.recalldesk.domain.documents.DocumentTask;
import com.recalldesk.domain.port.persistence.DocumentTaskRepository;
import com.recalldesk.domain.port.queue.DocumentTaskQueue;
import com.recalldesk.domain.port.ops.UnitOfWork;
import com.recalldesk.domain.task.TaskPolicy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * 任务发布者：把 document_tasks 的 PENDING 任务投递到文档索引队列。
 *
 * 后台循环在 {@link BasePublisher}，这里只回答「领哪张表、往哪条队列投」。
 * 投递失败按 attempts 走指数退避（退避基数是仓储自己的事，见 recordFailure），
 * 超限则把任务钉成终态，不再无限重投。
 */
public class DocumentTaskPublisher extends BasePublisher {

    private static final Logger log = LoggerFactory.getLogger(DocumentTaskPublisher.class);

    private final DocumentTaskRepository outbox;
    private final DocumentTaskQueue queue;

    public DocumentTaskPublisher(
            UnitOfWork unitOfWork, DocumentTaskRepository outbox, DocumentTaskQueue queue, TaskPolicy policy) {
        super(unitOfWork, policy, queue);
        this.outbox = outbox;
        this.queue = queue;
    }

    @Override
    public int publishPendingOnce() {
        Integer published = unitOfWork().executeFor(() -> {
            int count = 0;
            for (DocumentTask entry : outbox.listPending(policy().publishBatchSize())) {
                count += publishOne(entry);
            }
            return count;
        });
        return published == null ? 0 : published;
    }

    /** 成功标 QUEUE；失败记一次错误，超限标 FAILED。 */
    int publishOne(DocumentTask entry) {
        try {
            queue.enqueue(entry.id(), entry.documentId());
        } catch (RuntimeException exc) {
            outbox.recordFailure(entry.id(), TaskErrors.describe(exc));
            if (entry.attempts() + 1 >= policy().maxAttempts()) {
                outbox.markFailed(entry.id());
                log.error("任务投递失败达到上限: task={} doc={}", entry.id(), entry.documentId());
            }
            return 0;
        }
        outbox.markQueued(entry.id());
        return 1;
    }
}
