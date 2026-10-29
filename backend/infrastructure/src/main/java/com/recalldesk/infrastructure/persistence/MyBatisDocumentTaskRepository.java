package com.recalldesk.infrastructure.persistence;

import com.recalldesk.domain.documents.DocumentTaskStatus;
import com.recalldesk.domain.documents.DocumentTask;
import com.recalldesk.domain.port.persistence.DocumentTaskRepository;
import com.recalldesk.infrastructure.persistence.mapper.DocumentTaskMapper;
import com.recalldesk.infrastructure.persistence.row.DocumentTaskRow;
import java.util.List;
import java.util.Optional;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Repository;

/** document_tasks 表（发件箱）的 MyBatis-Plus 实现。 */
@Repository
public class MyBatisDocumentTaskRepository implements DocumentTaskRepository {

    /** last_error 的落库上限：错误文本可能是整段堆栈，超长会把行撑爆。 */
    private static final int MAX_ERROR_LENGTH = 2000;

    private final DocumentTaskMapper mapper;
    private final double retryBackoffBaseSeconds;

    public MyBatisDocumentTaskRepository(
            DocumentTaskMapper mapper,
            @Value("${recalldesk.task.retry-backoff-base-seconds}") double retryBackoffBaseSeconds) {
        this.mapper = mapper;
        this.retryBackoffBaseSeconds = retryBackoffBaseSeconds;
    }

    @Override
    public void add(String documentId) {
        DocumentTaskRow row = new DocumentTaskRow();
        row.setId(java.util.UUID.randomUUID().toString());
        row.setDocumentId(documentId);
        row.setStatus(DocumentTaskStatus.PENDING.wire());
        row.setAttempts(0);
        mapper.insert(row);
    }

    @Override
    public Optional<DocumentTask> get(String entryId) {
        return Optional.ofNullable(mapper.selectById(entryId)).map(DocumentTaskRow::toDomain);
    }

    @Override
    public List<DocumentTask> listPending(int limit) {
        return mapper.listPendingForUpdate(limit).stream().map(DocumentTaskRow::toDomain).toList();
    }

    @Override
    public void markQueued(String entryId) {
        mapper.markQueued(entryId);
    }

    @Override
    public void markSuccess(String entryId) {
        mapper.markSuccess(entryId);
    }

    @Override
    public void recordFailure(String entryId, String error) {
        mapper.recordFailure(entryId, truncate(error), retryBackoffBaseSeconds);
    }

    @Override
    public void markFailed(String entryId) {
        mapper.markFailed(entryId);
    }

    private static String truncate(String error) {
        return error == null || error.length() <= MAX_ERROR_LENGTH ? error : error.substring(0, MAX_ERROR_LENGTH);
    }

}
