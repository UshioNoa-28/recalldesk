package com.recalldesk.infrastructure.persistence.row;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.recalldesk.domain.documents.DocumentTask;
import com.recalldesk.domain.documents.DocumentTaskStatus;
import java.time.Instant;
import lombok.Data;

/** document_tasks 表的一行（索引任务发件箱）。 */
@Data
@TableName("document_tasks")
public class DocumentTaskRow {

    @TableId(type = IdType.INPUT)
    private String id;

    private String documentId;
    private String status;
    private Integer attempts;
    private String lastError;
    private Instant nextRetryAt;
    private Instant createdAt;
    private Instant queuedAt;

    public DocumentTask toDomain() {
        return new DocumentTask(
                id, documentId, DocumentTaskStatus.from(status), attempts == null ? 0 : attempts,
                lastError, createdAt, queuedAt);
    }
}
