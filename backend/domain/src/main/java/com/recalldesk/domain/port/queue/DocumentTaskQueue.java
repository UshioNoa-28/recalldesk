package com.recalldesk.domain.port.queue;

/**
 * 文档索引任务队列（anna_rag_document_tasks）。
 *
 * 单个 enqueue 方法就足以让 DI 按类型区分注入，避免把一类任务投到另一类的队列里；
 * 三个子接口各自独立，是因为它们的消息字段不同。
 */
public interface DocumentTaskQueue extends StreamQueue {

    /** 发布一条文档索引任务，返回消息 ID。 */
    String enqueue(String taskId, String documentId);
}
