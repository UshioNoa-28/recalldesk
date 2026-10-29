package com.recalldesk.application.worker;

import static org.assertj.core.api.Assertions.assertThat;

import com.recalldesk.application.FakeTransactionManager;
import com.recalldesk.application.worker.PortStubs.FakeEvalRunTaskQueue;
import com.recalldesk.application.worker.PortStubs.StubEvalRunRepository;
import com.recalldesk.application.worker.PortStubs.StubEvalRunTaskRepository;
import com.recalldesk.domain.eval.EvalRun;
import com.recalldesk.domain.eval.EvalRunConfig;
import com.recalldesk.domain.eval.EvalRunStatus;
import com.recalldesk.domain.eval.EvalRunTask;
import com.recalldesk.domain.eval.EvalTaskStatus;
import com.recalldesk.domain.task.TaskPolicy;
import java.time.Instant;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * EvalRunTaskPublisher 投递逻辑测试（假队列 + 假逐题任务仓储 + 假 run 仓储）：
 * {@code tests/test_eval_run_task_publisher.py} 逐条对应。
 *
 * 与出题 publisher 同族，但收尾不同：投递超限标 FAILED 后必须试一次收尾，
 * 否则「最后一题恰好投不出去」会让 run 永远停在 running。
 */
class EvalRunTaskPublisherTest {

    private static final TaskPolicy POLICY =
            new TaskPolicy("anna_rag_eval_run_tasks", "anna_rag_eval_run_workers", 1.0, 50, 3, 10.0);
    private static final Instant NOW = Instant.parse("2026-09-12T00:00:00Z");

    private static EvalRun runningRun() {
        return new EvalRun("run-1", "user-1", "ts-1", EvalRunStatus.RUNNING,
                new EvalRunConfig(5, false, false, null), null, null, NOW, null, 0, 1);
    }

    private static EvalRunTask entry(int attempts) {
        return new EvalRunTask("task-1", "run-1", "item-1", EvalTaskStatus.PENDING, attempts, null, NOW, null);
    }

    private static EvalRunTaskPublisher publisher(FakeTransactionManager transactions, StubEvalRunTaskRepository tasks,
            StubEvalRunRepository evals, FakeEvalRunTaskQueue queue) {
        return new EvalRunTaskPublisher(transactions.unitOfWork(), tasks, evals, queue, POLICY);
    }

    @Test
    @DisplayName("投递成功：标 QUEUE，不 finalize")
    void successMarksQueuedWithoutFinalizing() {
        FakeEvalRunTaskQueue queue = new FakeEvalRunTaskQueue();
        StubEvalRunTaskRepository tasks = new StubEvalRunTaskRepository();
        StubEvalRunRepository evals = new StubEvalRunRepository();

        int published = publisher(new FakeTransactionManager(), tasks, evals, queue).publishOne(entry(0));

        assertThat(published).isEqualTo(1);
        assertThat(queue.enqueued).containsExactly(Arrays.asList("task-1", "run-1", "item-1"));
        assertThat(tasks.queued).containsExactly("task-1");
        assertThat(evals.finalized).isEmpty();
    }

    @Test
    @DisplayName("投递失败未超限：退避重投，不 finalize")
    void failureBelowMaxRetriesWithoutFinalizing() {
        FakeEvalRunTaskQueue queue = new FakeEvalRunTaskQueue();
        queue.enqueueError = new IllegalStateException("redis down");
        StubEvalRunTaskRepository tasks = new StubEvalRunTaskRepository();
        StubEvalRunRepository evals = new StubEvalRunRepository();

        int published = publisher(new FakeTransactionManager(), tasks, evals, queue).publishOne(entry(0));

        assertThat(published).isEqualTo(0);
        assertThat(tasks.recordedFailures).containsExactly("task-1");
        assertThat(tasks.failedEntries).isEmpty();
        assertThat(evals.finalized).isEmpty();
    }

    @Test
    @DisplayName("投递失败到上限且无在途：标 FAILED 并收尾 run")
    void failureAtMaxFailsTaskAndSettlesRun() {
        FakeEvalRunTaskQueue queue = new FakeEvalRunTaskQueue();
        queue.enqueueError = new IllegalStateException("redis down");
        StubEvalRunTaskRepository tasks = new StubEvalRunTaskRepository();
        tasks.counts = Map.of("pending", 0, "queue", 0, "failed", 1, "success", 3);
        StubEvalRunRepository evals = new StubEvalRunRepository();
        evals.run = runningRun();

        int published = publisher(new FakeTransactionManager(), tasks, evals, queue)
                .publishOne(entry(POLICY.maxAttempts() - 1));

        assertThat(published).isEqualTo(0);
        assertThat(tasks.failedEntries).containsExactly("task-1");
        assertThat(evals.finalized).containsExactly(List.of("failed", "1 道题评测失败"));
    }

    @Test
    @DisplayName("还有在途任务时 finalize 收到非 0 pending_open，run 不会提前收尾")
    void failureAtMaxKeepsRunOpenIfTasksRemain() {
        FakeEvalRunTaskQueue queue = new FakeEvalRunTaskQueue();
        queue.enqueueError = new IllegalStateException("redis down");
        StubEvalRunTaskRepository tasks = new StubEvalRunTaskRepository();
        tasks.counts = Map.of("pending", 2, "queue", 0, "failed", 1);
        StubEvalRunRepository evals = new StubEvalRunRepository();
        evals.run = runningRun();

        publisher(new FakeTransactionManager(), tasks, evals, queue).publishOne(entry(POLICY.maxAttempts() - 1));

        assertThat(evals.finalized).isEmpty(); // 还有在途任务：这次不收尾
    }

    @Test
    @DisplayName("publishPendingOnce：整批投完只提交一次事务")
    void publishesBatchThenCommits() {
        FakeEvalRunTaskQueue queue = new FakeEvalRunTaskQueue();
        StubEvalRunTaskRepository tasks = new StubEvalRunTaskRepository();
        tasks.pending = List.of(entry(0), entry(0));
        StubEvalRunRepository evals = new StubEvalRunRepository();
        FakeTransactionManager transactions = new FakeTransactionManager();

        int published = publisher(transactions, tasks, evals, queue).publishPendingOnce();

        assertThat(published).isEqualTo(2);
        assertThat(queue.enqueued).containsExactly(
                Arrays.asList("task-1", "run-1", "item-1"),
                Arrays.asList("task-1", "run-1", "item-1"));
        assertThat(transactions.commits).isEqualTo(1);
    }

    @Test
    @DisplayName("退出信号已置位：run 立刻返回，不碰端口")
    void runStopsImmediatelyWhenStopSignalSet() {
        new EvalRunTaskPublisher(null, null, null, null, POLICY).run(new CountDownLatch(0));
    }
}
