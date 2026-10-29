package com.recalldesk.domain.port.persistence;

import com.recalldesk.domain.Page;
import com.recalldesk.domain.documents.Document;
import java.util.Optional;

/**
 * 文档元数据持久化能力。
 *
 * 事务边界不在这里：add/update/delete 只挂当前事务，提交由应用服务决定——
 * "文档行 + 发件箱任务"必须同进同退，仓储自己 commit 就守不住了。
 *
 * 除了 {@link #get(String)}，其余读写的 user_id 都由调用方（应用服务，它手上只有已验签的
 * 身份）给出，谓词落在 SQL 里而不是取回后在应用层比。之所以留一个不带归属的 {@code get}：
 * worker 手上只有任务行与文档 id，它的授权来自「这条任务是本系统自己写进 outbox 的」，
 * 不是来自某个用户。
 */
public interface DocumentRepository {

    void add(Document document);

    /** 内部路径（worker）用：worker 没有调用方身份，授权来自 outbox 本身。 */
    Optional<Document> get(String documentId);

    /** 面向调用方的读：不属于这个用户就是空——与「不存在」同一个答案，不给探测留缝隙。 */
    Optional<Document> getOwned(String userId, String documentId);

    /** 某用户的文档，按创建时间倒序分页，页码从 1 起。 */
    Page<Document> list(String userId, int page, int pageSize);

    /** 把实体最新状态整行写回；文档已不存在时抛 NoSuchElementException。 */
    void update(Document document);

    /** 带归属的删除：user_id 不匹配的行走不到这里，走到了也是 0 行受影响。 */
    boolean delete(String userId, String documentId);
}
