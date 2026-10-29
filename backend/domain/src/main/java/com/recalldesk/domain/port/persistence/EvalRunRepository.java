package com.recalldesk.domain.port.persistence;

import com.recalldesk.domain.eval.EvalRun;
import com.recalldesk.domain.eval.EvalRunConfig;
import com.recalldesk.domain.eval.EvalRunItem;
import com.recalldesk.domain.eval.EvalRunStatus;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * 一次评测 run 的持久化：建行、逐题结果、聚合收尾、重开。
 *
 * 与 EvalRepository（testsets/items）分家：run 侧只关心一次执行的建行、逐题回写、
 * 聚合成指标与重开；题面/坐标靠 join 现有表，不复制。事务边界同样由调用方持有。
 */
public interface EvalRunRepository {

    /** 创建一次运行，初始状态 running，config 是当时的检索配置快照。 */
    void createRun(String runId, String userId, String testsetId, EvalRunConfig config);

    /**
     * 写入一题的结果：一次一题而不是批量。
     *
     * 跑完一题就提交一题，轮询详情才看得到进度，中途挂掉也只丢当前这一题。
     * (runId, testsetItemIdd) 唯一，重复写会撞约束。
     */
    void recordRunItem(String runId, EvalRunItem result);

    /**
     * 结束运行：写聚合指标与 finishedAt。
     *
     * 条件写 {@code WHERE status = 'running'}：只有还活着的 run 能被收尾，所以重复调用
     * （以及和启动扫相撞）都是空操作，不会把已终态的 run 改回去。
     */
    void finishRun(String runId, EvalRunStatus status, Map<String, Object> metrics, String errorMessage);

    /** 按 id 取一行 run（含派生进度，不含逐题结果）：worker 专用，授权由它的调用方完成。 */
    Optional<EvalRun> getRun(String runId);

    /** 运行详情；不属于该用户就是不存在（别人的 run 与不存在的 run 同一个答案）。 */
    Optional<EvalRun> getRunOwned(String userId, String runId);

    /**
     * 逐题结果，题面与坐标联查带出。
     *
     * 走 inner join：题目被级联删（它指向的文档没了）则它的结果也不再指向任何
     * 可复核的东西，跟着一起消失比留下对不上号的行诚实。
     */
    List<EvalRunItem> listRunItems(String runId);

    /** 某测试集的历史运行（含进度，不含逐题结果），按创建时间降序。 */
    List<EvalRun> listRuns(String userId, String testsetId);

    /** 这题在本次 run 里结没结果：消费者的 redelivery 幂等守卫。 */
    boolean hasRunResult(String runId, String testsetItemId);

    /**
     * 删掉包含「以该文档为出处」的题目的 run，返回删除数；run 的 items / tasks 随之级联。
     *
     * 删文档的级联入口：题目消失后 run 的分母就对不上了，running 的 run 还会因为任务行
     * 被级联删而永远收不了尾，一起删掉是唯一自洽的状态。
     */
    int deleteRunsReferencingDocument(String documentId);


    /**
     * failed 的 run 重跑前翻回 running：清 error/finishedAt。
     *
     * 条件写 {@code WHERE status = 'failed'}——已 running/已 done 都是空操作；
     * "一个测试集最多一个 running"的部分唯一索引仍然兜并发。
     */
    void reopenRun(String runId);
}
