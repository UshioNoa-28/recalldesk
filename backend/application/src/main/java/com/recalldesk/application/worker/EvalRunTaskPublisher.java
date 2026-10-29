package com.recalldesk.application.worker;

import com.recalldesk.domain.eval.EvalRunTask;
import com.recalldesk.domain.port.persistence.EvalRunRepository;
import com.recalldesk.domain.port.persistence.EvalRunTaskRepository;
import com.recalldesk.domain.port.queue.EvalRunTaskQueue;
import com.recalldesk.domain.port.ops.UnitOfWork;
import com.recalldesk.domain.task.TaskPolicy;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import com.recalldesk.domain.eval.EvalRun;
import com.recalldesk.domain.eval.EvalRunStatus;
import java.util.Optional;
import com.recalldesk.application.eval.EvalMetrics;

/**
 * 逐题评测任务发布者：把 eval_run_tasks 的 PENDING 投递到 Eval Run Stream。
 *
 * 轮询循环与索引链路共用 {@link BasePublisher}，差异只在收尾：投递超限把任务标
 * FAILED 后，必须试一次 finalizeRun —— 否则「最后一题」恰恰投递失败时，
 * run 会因为数不到在途任务而永远停在 running。
 */
public class EvalRunTaskPublisher extends BasePublisher {

    private static final Logger log = LoggerFactory.getLogger(EvalRunTaskPublisher.class);

    private final EvalRunTaskRepository tasks;
    private final EvalRunRepository evals;
    private final EvalRunTaskQueue queue;

    public EvalRunTaskPublisher(
            UnitOfWork unitOfWork,
            EvalRunTaskRepository tasks,
            EvalRunRepository evals,
            EvalRunTaskQueue queue,
            TaskPolicy policy) {
        super(unitOfWork, policy, queue);
        this.tasks = tasks;
        this.evals = evals;
        this.queue = queue;
    }

    @Override
    public int publishPendingOnce() {
        Integer published = unitOfWork().executeFor(() -> {
            int count = 0;
            for (EvalRunTask entry : tasks.listPending(policy().publishBatchSize())) {
                count += publishOne(entry);
            }
            return count;
        });
        return published == null ? 0 : published;
    }

    /** 投递单条任务：成功标 QUEUE，失败退避，超限终态并收尾 run。 */
    int publishOne(EvalRunTask entry) {
        try {
            queue.enqueue(entry.id(), entry.runId(), entry.itemId());
        } catch (RuntimeException exc) {
            tasks.recordFailure(entry.id(), TaskErrors.describe(exc));
            if (entry.attempts() + 1 >= policy().maxAttempts()) {
                tasks.markFailed(entry.id());
                // 收尾要拿最新的全局计数：本次刚标的 FAILED 行在同一事务里可见
                Map<String, Integer> counts = tasks.countByStatus(entry.runId());
                int pendingOpen = counts.getOrDefault("pending", 0) + counts.getOrDefault("queue", 0);
                int failed = counts.getOrDefault("failed", 0);
                if (pendingOpen == 0) {
                    Optional<EvalRun> run = evals.getRun(entry.runId());
                    if (run.isPresent() && run.get().status() == EvalRunStatus.RUNNING) {
                        evals.finishRun(
                                entry.runId(),
                                failed > 0 ? EvalRunStatus.FAILED : EvalRunStatus.DONE,
                                failed > 0 ? null : EvalMetrics.aggregate(evals.listRunItems(entry.runId()), run.get().config().topK()),
                                failed > 0 ? failed + " 道题评测失败" : null);
                    }
                }
                log.error(
                        "评测任务投递失败达到上限: task={} run={} item={}",
                        entry.id(),
                        entry.runId(),
                        entry.itemId());
            }
            return 0;
        }
        tasks.markQueued(entry.id());
        return 1;
    }
}
