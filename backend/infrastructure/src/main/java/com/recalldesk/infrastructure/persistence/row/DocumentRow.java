package com.recalldesk.infrastructure.persistence.row;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.recalldesk.domain.documents.Document;
import com.recalldesk.domain.documents.DocumentStatus;
import java.time.Instant;
import lombok.Data;

/** documents 表的一行。created_at 交给库的 DEFAULT now()，插入时留 null 即可。 */
@Data
@TableName("documents")
public class DocumentRow {

    @TableId(type = IdType.INPUT)
    private String id;

    private String userId;
    private String name;
    private String storageKey;
    private Long sizeBytes;
    private String mediaType;
    private String status;
    private Integer chunkCount;
    private String errorMessage;
    private Instant createdAt;
    private Instant indexedAt;

    /** 领域对象 → 行：写库前的唯一转换点。 */
    public static DocumentRow from(Document document) {
        DocumentRow row = new DocumentRow();
        row.setId(document.id());
        row.setUserId(document.userId());
        row.setName(document.name());
        row.setStorageKey(document.storageKey());
        row.setSizeBytes(document.sizeBytes());
        row.setMediaType(document.mediaType());
        row.setStatus(document.status().wire());
        row.setChunkCount(document.chunkCount());
        row.setErrorMessage(document.errorMessage());
        row.setCreatedAt(document.createdAt());
        row.setIndexedAt(document.indexedAt());
        return row;
    }

    /** 行 → 领域对象：读库后的唯一转换点。 */
    public Document toDomain() {
        return new Document(
                id, userId, name, storageKey, sizeBytes, mediaType,
                DocumentStatus.from(status), chunkCount, errorMessage, createdAt, indexedAt);
    }
}
