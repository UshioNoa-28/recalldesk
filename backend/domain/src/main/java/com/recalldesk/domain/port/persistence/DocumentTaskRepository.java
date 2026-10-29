package com.recalldesk.domain.port.persistence;

import com.recalldesk.domain.documents.DocumentTask;
import java.util.List;
import java.util.Optional;

/** 任务发件箱（Transactional Outbox）端口。 */
public interface DocumentTaskRepository {

    /** 向当前事务追加一条 PENDING 索引任务。 */
    void add(String documentId);

    Optional<DocumentTask> get(String entryId);

    /**
     * 读取已到重试时间的 PENDING 任务，按创建时间升序。
     *
     * FOR UPDATE SKIP LOCKED：多个 publisher 副本并发时各取各的，不会把同一行重复投递。
     * 调用方必须在同一事务里完成 markQueued + 提交，锁才覆盖投递窗口。
     */
    List<DocumentTask> listPending(int limit);

    /** PENDING → QUEUE，记录投递时间并清掉上一次的错误。 */
    void markQueued(String entryId);

    /** QUEUE → SUCCESS。 */
    void markSuccess(String entryId);

    /** attempts+1、状态回 PENDING、按指数退避设下次重试时间；超限终态由调用方随后 markFailed 覆盖。 */
    void recordFailure(String entryId, String error);

    /** 标记为终态 FAILED。 */
    void markFailed(String entryId);
}
