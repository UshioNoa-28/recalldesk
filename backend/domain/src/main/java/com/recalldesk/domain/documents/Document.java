package com.recalldesk.domain.documents;

import java.time.Instant;

/**
 * 一个上传文档的元数据。索引状态机：pending → success / failed，重索引把三态打回 pending。
 *
 * 不可变：状态流转靠带语义的拷贝方法，而不是就地改字段；
 * 这里换成带语义的拷贝方法，状态转移点（consumer 的三条分支、service 的重索引）逐个对得上，
 * 少一处"改了字段忘了 update"这类静默不一致。
 *
 * {@code userId} 是归属，一旦写下永不迁移：所有拷贝方法都原样带过去，没有
 * 「transferOwner」这种东西。它同时被冗余进 chunks 表（检索要把归属下推进索引），
 * 那份只由 reindex 链路从这一行抄写，不是第二个真相源。
 */
public record Document(
        String id,
        String userId,
        String name,
        String storageKey,
        long sizeBytes,
        String mediaType,
        DocumentStatus status,
        Integer chunkCount,
        String errorMessage,
        Instant createdAt,
        Instant indexedAt) {

    public Document markIndexed(int newChunkCount, Instant at) {
        return new Document(
                id, userId, name, storageKey, sizeBytes, mediaType,
                DocumentStatus.SUCCESS, newChunkCount, null, createdAt, at);
    }

    public Document markFailed(String error) {
        return new Document(
                id, userId, name, storageKey, sizeBytes, mediaType,
                DocumentStatus.FAILED, chunkCount, error, createdAt, null);
    }

    /** 重新索引：清掉上一轮的结论，等 worker 重新写回。 */
    public Document resetForReindex() {
        return new Document(
                id, userId, name, storageKey, sizeBytes, mediaType,
                DocumentStatus.PENDING, null, null, createdAt, null);
    }
}
