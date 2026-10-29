package com.recalldesk.domain.port.persistence;

import com.recalldesk.domain.eval.EvalRunTask;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * 逐题评测任务发件箱（eval_run_tasks）端口：run 的 publisher / worker 侧数据访问。
 *
 * 只管任务本身；run 状态与逐题结果的读写在 EvalRunRepository。
 * 一次 run 开跑 fan-out 一题一行，重试是复位这一行而不是补发新行。
 */
public interface EvalRunTaskRepository {

    /**
     * 向当前事务追加一条 PENDING 任务（一个 run 内每题唯一）。
     *
     */
    void add(String runId, String itemId);

    Optional<EvalRunTask> get(String taskId);

    /**
     * 领取一批到期的 PENDING 任务（FOR UPDATE SKIP LOCKED），按创建时间升序。
     *
     * 锁持有到本事务提交，多 publisher 并发各取各的；调用方须同事务内 markQueued + 提交。
     */
    List<EvalRunTask> listPending(int limit);

    /** PENDING → QUEUE，记录投递时间并清掉上一次的错误。 */
    void markQueued(String taskId);

    /** QUEUE → SUCCESS。 */
    void markSuccess(String taskId);

    /** attempts+1、状态回 PENDING、按指数退避设下次重试时间；超限终态由调用方随后 markFailed 覆盖。 */
    void recordFailure(String taskId, String error);

    /** 标记为终态 FAILED。 */
    void markFailed(String taskId);

    /** 把该 run 里终态 FAILED 的任务复位回 PENDING（重试三件套清零），返回条数。 */
    int resetFailedForRun(String runId);

    /** 某 run 的任务按状态计数：finalizeRun 判断"还有没有在途任务"用。 */
    Map<String, Integer> countByStatus(String runId);
}
