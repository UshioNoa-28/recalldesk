package com.recalldesk.application.worker;

import static org.assertj.core.api.Assertions.assertThat;

import com.recalldesk.application.FakeTransactionManager;
import com.recalldesk.application.worker.PortStubs.FakeDocumentTaskQueue;
import com.recalldesk.application.worker.PortStubs.StubDocumentTaskRepository;
import com.recalldesk.domain.documents.DocumentTask;
import com.recalldesk.domain.documents.DocumentTaskStatus;
import com.recalldesk.domain.task.TaskPolicy;
import java.time.Instant;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * DocumentTaskPublisher 投递逻辑测试（假队列 + 假发件箱）：
 * {@code tests/test_task_publisher.py} 逐条对应：
 * 成功标 QUEUE；失败记一次错误、未超限不标终态、超限标 FAILED；
 * 一批投完统一提交一次；退出信号已置位时 run 立刻返回。
 */
class DocumentTaskPublisherTest {

    /** 与 application.yml 的 recalldesk.streams.document 默认值同源（写死在这里，改默认是一次有意的编辑）。 */
    private static final TaskPolicy POLICY =
            new TaskPolicy("anna_rag_document_tasks", "anna_rag_document_workers", 0.5, 50, 10, 30.0);
    private static final Instant NOW = Instant.parse("2026-09-12T00:00:00Z");

    private static DocumentTask entry(String taskId, int attempts) {
        return new DocumentTask(taskId, "doc-1", DocumentTaskStatus.PENDING, attempts, null, NOW, null);
    }

    private static DocumentTaskPublisher publisher(FakeTransactionManager transactions, StubDocumentTaskRepository outbox,
            FakeDocumentTaskQueue queue) {
        return new DocumentTaskPublisher(transactions.unitOfWork(), outbox, queue, POLICY);
    }

    @Test
    @DisplayName("投递成功：标 QUEUE，返回 1")
    void publishSuccessMarksQueued() {
        FakeDocumentTaskQueue queue = new FakeDocumentTaskQueue();
        StubDocumentTaskRepository outbox = new StubDocumentTaskRepository();

        int result = publisher(new FakeTransactionManager(), outbox, queue).publishOne(entry("task-1", 0));

        assertThat(result).isEqualTo(1);
        assertThat(queue.enqueued).containsExactly(Arrays.asList("task-1", "doc-1"));
        assertThat(outbox.queued).containsExactly("task-1");
    }

    @Test
    @DisplayName("积压播报：领满一整批就去读未确认数，没满且不心跳就不读")
    void backlogIsReportedOnlyWhenItSaysSomething() {
        FakeDocumentTaskQueue queue = new FakeDocumentTaskQueue();
        queue.unacked = 120;
        DocumentTaskPublisher publisher = publisher(new FakeTransactionManager(), new StubDocumentTaskRepository(), queue);

        publisher.reportBacklog(POLICY.publishBatchSize());
        assertThat(queue.pendingChecks).isEqualTo(1);

        // 一轮没投满、心跳也没到点：什么都不必问，0.5s 一次的循环不该把 Redis 当仪表盘轮
        publisher.reportBacklog(3);
        assertThat(queue.pendingChecks).isEqualTo(1);
    }

    @Test
    @DisplayName("投递失败未超限：记一次错误，不标终态（等退避重投）")
    void publishFailureBelowMaxKeepsPending() {
        FakeDocumentTaskQueue queue = new FakeDocumentTaskQueue();
        queue.enqueueError = new IllegalStateException("redis down");
        StubDocumentTaskRepository outbox = new StubDocumentTaskRepository();

        int result = publisher(new FakeTransactionManager(), outbox, queue).publishOne(entry("task-1", 1));

        assertThat(result).isEqualTo(0);
        assertThat(outbox.recordedFailures).containsExactly("task-1");
        assertThat(outbox.failedEntries).isEmpty();
    }

    @Test
    @DisplayName("投递失败到上限：标 FAILED")
    void publishFailureAtMaxMarksFailed() {
        FakeDocumentTaskQueue queue = new FakeDocumentTaskQueue();
        queue.enqueueError = new IllegalStateException("redis down");
        StubDocumentTaskRepository outbox = new StubDocumentTaskRepository();

        int result = publisher(new FakeTransactionManager(), outbox, queue)
                .publishOne(entry("task-1", POLICY.maxAttempts() - 1));

        assertThat(result).isEqualTo(0);
        assertThat(outbox.failedEntries).containsExactly("task-1");
    }

    @Test
    @DisplayName("publishPendingOnce：整批投完只提交一次事务")
    void publishesAllPendingAndCommitsOnce() {
        FakeDocumentTaskQueue queue = new FakeDocumentTaskQueue();
        StubDocumentTaskRepository outbox = new StubDocumentTaskRepository();
        outbox.pending = List.of(entry("task-1", 0), entry("task-2", 0));
        FakeTransactionManager transactions = new FakeTransactionManager();

        int published = publisher(transactions, outbox, queue).publishPendingOnce();

        assertThat(published).isEqualTo(2);
        assertThat(queue.enqueued).containsExactly(
                Arrays.asList("task-1", "doc-1"),
                Arrays.asList("task-2", "doc-1"));
        assertThat(outbox.queued).containsExactly("task-1", "task-2");
        assertThat(transactions.commits).isEqualTo(1);
    }

    @Test
    @DisplayName("退出信号已置位：run 立刻返回，不碰端口")
    void runStopsImmediatelyWhenStopSignalSet() {
        // 端口全给 null：只要循环不该跑，就一次也不该碰它们
        new DocumentTaskPublisher(null, null, null, POLICY).run(new CountDownLatch(0));
    }
}
