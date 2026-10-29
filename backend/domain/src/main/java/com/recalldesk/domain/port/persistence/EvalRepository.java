package com.recalldesk.domain.port.persistence;

import com.recalldesk.domain.eval.EvalTestSet;
import com.recalldesk.domain.eval.EvalTestSetItem;
import java.util.List;
import java.util.Optional;

/**
 * 评测集与题目的持久化能力（run 侧在 EvalRunRepository，出箱任务在 EvalRunTaskRepository）。
 *
 * 纯数据访问：不提交事务，边界由调用方（service / worker）控制。
 *
 * 读路径一律带 userId：这不是防御性的参数噪声，越权读到别人的题目就是泄漏金标答案。
 * 只有 worker 用的 {@link #getItem(String)} 不带——它手上只有 item_id，授权由上一层
 * （run 行的归属）完成，这里是链路的信任边界。
 */
public interface EvalRepository {

    // ---- testsets ----

    void createTestSet(String testSetId, String userId, String name);

    /** 单条评测集元信息（不含 items）；不属于该用户就是不存在。 */
    Optional<EvalTestSet> getTestSet(String userId, String testSetId);

    /** 某用户的评测集列表，按创建时间降序。 */
    List<EvalTestSet> listTestSets(String userId);

    void deleteTestSet(String userId, String testSetId);

    // ---- items ----

    /**
     * 批量写入题目与其引文。
     *
     * 进来就是终态：query 已经由调用方校验非空，引文坐标也已经解析完——落库这里不再有
     * 「半成品题目」这一种状态，所以表上没有 status/error_message。
     */
    void addItems(String testSetId, List<EvalTestSetItem> items);

    /** 题目列表（按写入顺序），含每题的金标 chunk。 */
    List<EvalTestSetItem> listTestSetItems(String testSetId);

    /** 按 ID 查单条题目（含金标）：worker 手上只有 item_id。 */
    Optional<EvalTestSetItem> getItem(String itemId);

    /** 删掉把该文档当证据的任何题目，返回删除数。删文档的应用层用例必须在同一事务里先调它。 */
    int deleteItemsReferencingDocument(String documentId);
}
