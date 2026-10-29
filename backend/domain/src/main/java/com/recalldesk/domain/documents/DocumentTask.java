package com.recalldesk.domain.documents;

import java.time.Instant;

/**
 * document_tasks 表的一行：一条待投递/已投递的索引任务。
 */
public record DocumentTask(
        String id,
        String documentId,
        DocumentTaskStatus status,
        int attempts,
        String lastError,
        Instant createdAt,
        Instant queuedAt) {
}
