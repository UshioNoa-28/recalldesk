package com.recalldesk.application.worker;

import com.recalldesk.application.search.dto.SearchOutcome;
import com.recalldesk.application.search.SearchService;
import com.recalldesk.application.eval.EvalMetrics;
import com.recalldesk.domain.eval.EvalRun;
import com.recalldesk.domain.eval.EvalRunItem;
import com.recalldesk.domain.eval.EvalRunStatus;
import com.recalldesk.domain.eval.EvalRunTask;
import com.recalldesk.domain.eval.EvalTaskStatus;
import com.recalldesk.domain.eval.EvalTestSetItem;
import com.recalldesk.domain.port.persistence.EvalRepository;
import com.recalldesk.domain.port.persistence.EvalRunRepository;
import com.recalldesk.domain.port.persistence.EvalRunTaskRepository;
import com.recalldesk.domain.port.queue.EvalRunTaskQueue;
import com.recalldesk.domain.port.ops.UnitOfWork;
import com.recalldesk.application.search.FusionSpec;
import com.recalldesk.application.search.dto.SearchProfile;
import com.recalldesk.domain.task.TaskFields;
import com.recalldesk.domain.task.TaskPolicy;
import java.util.Map;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * 逐题评测消费者：从 Eval Run Stream 领任务，检索一次、打分一行、落定后收尾。
 *
 * 设计说明（与出题消费者同一族规，消费循环 / ACK 规则见 {@link BaseConsumer}）：
 * - 一次任务两段事务：领取校验（短）→ 检索（慢 I/O，不占 DB 连接）→ 回写（短）；
 * - 重投安全靠幂等：任务已终态跳过、结果行已存在跳过（hasRunResult）；
 * - run 不再是「一个进程的循环」：每行 run_items 落库进度就 +1（进度是数出来的），
 *   聚合指标与收尾由 finalizeRun 在「该 run 无在途任务」时做一次，谁最后谁收尾；
 * - 检索失败：attempts+1、任务回 PENDING（指数退避由 publisher 重投），超限任务
 *   标 FAILED 并触发 finalize —— run 收成 failed 而不是永远挂着；
 * - 题目在 run 期间被重置（retry_failed_items 清掉 query）或消失：重试变不出题面，
 *   按永久失败处理，同样走 finalize。
 */
public class EvalRunConsumer extends BaseConsumer {

    private static final Logger log = LoggerFactory.getLogger(EvalRunConsumer.class);

    private static final String CONSUMER_NAME_PREFIX = "eval-run-consumer";

    /** 领取事务里备好的检索料：慢 I/O 之前把数据库连接还给池。 */
    private record PendingWork(
            /** 检索视野由 run 的归属决定，不是由消息里谁的 token 决定：任务行属于谁就查谁的块。 */
            String userId,
            int topK,
            SearchProfile profile,
            String query,
            EvalTestSetItem item) {}

    private final EvalRunTaskRepository runTasks;
    private final EvalRunRepository runs;
    private final EvalRepository catalog;
    private final SearchService searchService;

    public EvalRunConsumer(
            EvalRunTaskQueue queue,
            UnitOfWork unitOfWork,
            TaskPolicy policy,
            EvalRunTaskRepository runTasks,
            EvalRunRepository runs,
            EvalRepository catalog,
            SearchService searchService) {
        this(queue, unitOfWork, policy, runTasks, runs, catalog, searchService, null);
    }

    public EvalRunConsumer(
            EvalRunTaskQueue queue,
            UnitOfWork unitOfWork,
            TaskPolicy policy,
            EvalRunTaskRepository runTasks,
            EvalRunRepository runs,
            EvalRepository catalog,
            SearchService searchService,
            String consumerName) {
        super(queue, unitOfWork, policy, CONSUMER_NAME_PREFIX, consumerName);
        this.runTasks = runTasks;
        this.runs = runs;
        this.catalog = catalog;
        this.searchService = searchService;
    }

    @Override
    protected Map<String, String> extractTaskIds(Map<String, String> fields) {
        String taskId = fields.get("task_id");
        String runId = fields.get("run_id");
        String itemId = fields.get("item_id");
        if (TaskFields.missing(taskId) || TaskFields.missing(runId) || TaskFields.missing(itemId)) {
            return null;
        }
        return fields("task_id", taskId, "run_id", runId, "item_id", itemId);
    }

    /** 跑一题：领取校验 → 检索 → 回写落定。业务失败落库后正常返回。 */
    @Override
    protected void handleTask(Map<String, String> ids) {
        String taskId = ids.get("task_id");
        String runId = ids.get("run_id");
        String itemId = ids.get("item_id");

        // ---- 领取事务：校验 + 取料，慢 I/O 之前把连接还给池 ----
        PendingWork work = unitOfWork().executeFor(() -> prepare(taskId, runId, itemId));
        if (work == null) {
            return; // 领取段已经短路（或已收尾），不需要检索
        }

        // ---- 慢 I/O：一次检索，不占 DB 连接 ----
        EvalRunItem result;
        try {
            long started = System.nanoTime();
            SearchOutcome outcome = searchService.search(work.query(), work.topK(), work.profile(), work.userId());
            double latencyMs = (System.nanoTime() - started) / 1_000_000.0;
            result = EvalMetrics.scoreQuery(work.item(), outcome.hits(), work.topK(), latencyMs, outcome.channels());
        } catch (RuntimeException exc) {
            recordSearchFailure(taskId, runId, exc);
            return;
        }

        // ---- 回写事务：一题一行一提交，轮询详情才看得到进度 ----
        unitOfWork().execute(() -> {
            runs.recordRunItem(runId, result);
            runTasks.markSuccess(taskId);
            finalizeRun(runId);
        });
    }

    /** 领取校验 + 取料；返回 null 表示这条消息已被消费掉（各短路分支自己落库）。 */
    private PendingWork prepare(String taskId, String runId, String itemId) {
        Optional<EvalRunTask> taskFound = runTasks.get(taskId);
        if (taskFound.isEmpty()) {
            // 任务行没了（run 或题目被级联删）：这条消息就是它存在的最后痕迹。
            // 试着收尾一次 —— 如果它是最后一条在途的，run 不该继续挂着。
            finalizeRun(runId);
            return null;
        }
        EvalRunTask task = taskFound.get();
        if (task.status() == EvalTaskStatus.SUCCESS || task.status() == EvalTaskStatus.FAILED) {
            return null; // 幂等：redelivery，上一手已经把回写和收尾一起提交了
        }

        Optional<EvalRun> runFound = runs.getRun(runId);
        if (runFound.isEmpty() || runFound.get().status() != EvalRunStatus.RUNNING) {
            runTasks.markSuccess(taskId); // 无事可做也算消费掉
            return null;
        }
        if (runs.hasRunResult(runId, itemId)) {
            // 结果行在而任务没落定：上一手提交到一半崩了。补记 + 收尾，不再检索。
            runTasks.markSuccess(taskId);
            finalizeRun(runId);
            return null;
        }

        Optional<EvalTestSetItem> itemFound = catalog.getItem(itemId);
        if (itemFound.isEmpty() || TaskFields.missing(itemFound.get().query())) {
            // 题面没了（run 期间被重置/重出）：重试变不出题面，直接终态
            runTasks.recordFailure(taskId, "题目无题面（被重置或已删除）");
            runTasks.markFailed(taskId);
            finalizeRun(runId);
            log.error("题目缺题面，任务终态失败: task={} item={}", taskId, itemId);
            return null;
        }

        EvalRun run = runFound.get();
        EvalTestSetItem item = itemFound.get();
        // run 的配方就是这次检索的档位（消融实验：同题不同 run 只差这里）。
        // fusion 缺键走 FusionSpec 的代码默认（rrf, k=60）而不是装配默认：
        SearchProfile profile = new SearchProfile(
                run.config().queryRewrite(), run.config().rerank(), FusionSpec.fromConfig(run.config().fusion()));
        return new PendingWork(run.userId(), run.config().topK(), profile, item.query(), item);
    }

    /** 检索失败：退避重投，超限终态 + 收尾。 */
    private void recordSearchFailure(String taskId, String runId, RuntimeException exc) {
        String error = TaskErrors.describe(exc);
        unitOfWork().execute(() -> {
            runTasks.recordFailure(taskId, error);
            Optional<EvalRunTask> refreshed = runTasks.get(taskId);
            if (refreshed.isPresent() && refreshed.get().attempts() >= policy().maxAttempts()) {
                runTasks.markFailed(taskId);
                finalizeRun(runId);
                log.error("评测任务失败达到上限: task={} run={} error={}", taskId, runId, error);
            } else {
                // 带上第几次失败：重试次数是可观测事实，只报「未超限」等于让排障的人去翻库
                log.warn("评测任务失败（未超限，回 PENDING 等重投）: task={} attempts={} error={}",
                        taskId, refreshed.map(EvalRunTask::attempts).orElse(-1), error);
            }
        });
    }

    /** 数任务 → 落定则收尾。同事务内自己刚标的状态对自己可见。 */
    private void finalizeRun(String runId) {
        Map<String, Integer> counts = runTasks.countByStatus(runId);
        int pendingOpen = counts.getOrDefault("pending", 0) + counts.getOrDefault("queue", 0);
        int failed = counts.getOrDefault("failed", 0);
        if (pendingOpen > 0) {
            return; // 还有在途任务，收尾轮不到这次
        }
        Optional<EvalRun> run = runs.getRun(runId);
        if (run.isEmpty() || run.get().status() != EvalRunStatus.RUNNING) {
            return; // 已删除或已终态：重复/并发收尾都是空操作
        }
        if (failed > 0) {
            // 残缺指标不如没有：有题永久失败时不发布 DONE，
            // 免得 recall@k 用小分母冒充完整评测
            runs.finishRun(runId, EvalRunStatus.FAILED, null, failed + " 道题评测失败");
            return;
        }
        runs.finishRun(
                runId, EvalRunStatus.DONE, EvalMetrics.aggregate(runs.listRunItems(runId), run.get().config().topK()), null);
    }
}
