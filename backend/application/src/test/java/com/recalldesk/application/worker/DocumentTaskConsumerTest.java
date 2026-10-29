package com.recalldesk.application.worker;

import static org.assertj.core.api.Assertions.assertThat;

import com.recalldesk.application.FakeTransactionManager;
import com.recalldesk.application.document.IndexingService;
import com.recalldesk.application.worker.PortStubs.FakeDocumentTaskQueue;
import com.recalldesk.application.worker.PortStubs.StubDocumentRepository;
import com.recalldesk.application.worker.PortStubs.StubDocumentTaskRepository;
import com.recalldesk.application.worker.PortStubs.StubFileStorage;
import com.recalldesk.domain.documents.Document;
import com.recalldesk.domain.documents.DocumentStatus;
import com.recalldesk.domain.documents.DocumentTask;
import com.recalldesk.domain.documents.DocumentTaskStatus;
import com.recalldesk.domain.task.StreamMessage;
import com.recalldesk.domain.task.TaskPolicy;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.slf4j.MDC;
import org.junit.jupiter.api.Test;
import com.recalldesk.domain.exception.indexing.EmptyContentException;

/**
 * DocumentTaskConsumer 测试：
 * 处理任务的状态流转（成功 / 失败退避 / 超限终态 / 内容切不出块 / 文档已删）
 * 与消息层的 ACK 规则（缺字段 ACK、业务失败 ACK、提交失败不 ACK）。
 */
class DocumentTaskConsumerTest {

    private static final TaskPolicy POLICY =
            new TaskPolicy("anna_rag_document_tasks", "anna_rag_document_workers", 0.5, 50, 10, 30.0);
    private static final Instant NOW = Instant.parse("2026-09-12T00:00:00Z");
    /** 文档归属：worker 手上没有调用方身份，检索视野是从 documents 行抄进块里的。 */
    private static final String ALICE = "user-alice";

    private static Document document() {
        return new Document(
                "doc-1", ALICE, "notes.md", "uploads/doc-1", 10, "text/markdown",
                DocumentStatus.PENDING, null, null, NOW, null);
    }

    private static DocumentTask entry(int attempts) {
        return new DocumentTask("task-1", "doc-1", DocumentTaskStatus.QUEUE, attempts, null, NOW, NOW);
    }

    /** 假索引服务：IndexingService 是具体类，只覆写 ingest，端口一律不给。 */
    private static final class FakeIndexingService extends IndexingService {

        private final int chunkCount;
        private final RuntimeException error;
        final List<List<String>> ingested = new ArrayList<>();

        FakeIndexingService() {
            this(5, null);
        }

        FakeIndexingService(int chunkCount, RuntimeException error) {
            super(null, null, null, null);
            this.chunkCount = chunkCount;
            this.error = error;
        }

        @Override
        public int ingest(String documentId, String userId, String name, String text) {
            if (error != null) {
                throw error;
            }
            ingested.add(List.of(documentId, userId, name, text));
            return chunkCount;
        }
    }

    /** 用例脚手架：一套 fake 端口 + 一个消费者。 */
    private static final class Fixture {

        final FakeTransactionManager transactions = new FakeTransactionManager();
        final StubDocumentRepository documents = new StubDocumentRepository();
        final StubDocumentTaskRepository outbox = new StubDocumentTaskRepository();
        final StubFileStorage fileStorage = new StubFileStorage();
        final FakeDocumentTaskQueue queue = new FakeDocumentTaskQueue();
        final FakeIndexingService indexing;
        final DocumentTaskConsumer consumer;

        Fixture(IndexingService indexing) {
            this.indexing = (FakeIndexingService) indexing;
            this.documents.document = document();
            this.outbox.entry = entry(0);
            this.consumer = new DocumentTaskConsumer(
                    queue, transactions.unitOfWork(), POLICY, documents, outbox, fileStorage, indexing, "test-consumer");
        }
    }

    private static Fixture fixture() {
        return new Fixture(new FakeIndexingService());
    }

    private static Fixture fixture(FakeIndexingService indexing) {
        return new Fixture(indexing);
    }

    private static Map<String, String> ids(String... keyValues) {
        Map<String, String> ids = new LinkedHashMap<>();
        for (int index = 0; index < keyValues.length; index += 2) {
            ids.put(keyValues[index], keyValues[index + 1]);
        }
        return ids;
    }

    // ---- 处理任务本体 ----

    @Test
    @DisplayName("成功：任务标 success，文档标 SUCCESS 并写块数与索引时间")
    void successMarksTaskAndDocumentSuccess() {
        Fixture fixture = fixture();

        fixture.consumer.handleTask(ids("task_id", "task-1", "document_id", "doc-1"));

        assertThat(fixture.outbox.successes).containsExactly("task-1");
        Document updated = fixture.documents.updated.getLast();
        assertThat(updated.status()).isEqualTo(DocumentStatus.SUCCESS);
        assertThat(updated.chunkCount()).isEqualTo(5);
        assertThat(updated.indexedAt()).isNotNull();
        assertThat(fixture.transactions.commits).isEqualTo(1);
    }

    @Test
    @DisplayName("index 前先抽文本：入库的是解码后的文本，归属从 documents 行抄进块里")
    void extractsTextBeforeIndexing() {
        Fixture fixture = fixture();
        fixture.fileStorage.content = "正文一段。".getBytes(StandardCharsets.UTF_8);

        fixture.consumer.handleTask(ids("task_id", "task-1", "document_id", "doc-1"));

        assertThat(fixture.indexing.ingested)
                .containsExactly(List.of("doc-1", ALICE, "notes.md", "正文一段。"));
    }

    @Test
    @DisplayName("业务失败未超限：记一次错误，不标终态（回 PENDING 等重投）")
    void failureBelowMaxRecordsFailureAndReturns() {
        Fixture fixture = fixture(new FakeIndexingService(5, new IllegalStateException("embedding down")));
        fixture.outbox.entry = entry(POLICY.maxAttempts() - 2);

        fixture.consumer.handleTask(ids("task_id", "task-1", "document_id", "doc-1"));

        assertThat(fixture.outbox.recordedFailures).containsExactly("task-1");
        assertThat(fixture.outbox.failedEntries).isEmpty();
        assertThat(fixture.transactions.commits).isEqualTo(1); // 业务失败也提交（由调用方 ACK）
    }

    @Test
    @DisplayName("业务失败到上限：任务与文档都标 FAILED")
    void failureAtMaxMarksTaskAndDocumentFailed() {
        Fixture fixture = fixture(new FakeIndexingService(5, new IllegalStateException("embedding down")));
        fixture.outbox.entry = entry(POLICY.maxAttempts());

        fixture.consumer.handleTask(ids("task_id", "task-1", "document_id", "doc-1"));

        assertThat(fixture.outbox.failedEntries).containsExactly("task-1");
        assertThat(fixture.documents.updated.getLast().status()).isEqualTo(DocumentStatus.FAILED);
    }

    @Test
    @DisplayName("切不出分块：直接终态，不走退避（不用白跑满 10 次重试）")
    void emptyContentFailsImmediatelyWithoutBackoff() {
        Fixture fixture = fixture(new FakeIndexingService(
                0, new EmptyContentException("文档没有可索引的内容")));

        fixture.consumer.handleTask(ids("task_id", "task-1", "document_id", "doc-1"));

        assertThat(fixture.outbox.failedEntries).containsExactly("task-1");
        assertThat(fixture.outbox.recordedFailures).isEmpty(); // 没走退避路径
        Document updated = fixture.documents.updated.getLast();
        assertThat(updated.status()).isEqualTo(DocumentStatus.FAILED);
        assertThat(updated.errorMessage()).contains("EmptyContentException");
    }

    @Test
    @DisplayName("文档已不存在：任务直接算成功（幂等）")
    void missingDocumentMarksTaskSuccess() {
        Fixture fixture = fixture();
        fixture.documents.document = null;

        fixture.consumer.handleTask(ids("task_id", "task-1", "document_id", "doc-1"));

        assertThat(fixture.outbox.successes).containsExactly("task-1");
    }

    // ---- 消息层：字段校验与 ACK 规则 ----

    @Test
    @DisplayName("缺 task_id：直接 ACK 掉，不处理")
    void missingFieldsAcksAndSkips() {
        Fixture fixture = fixture();

        fixture.consumer.processSingleMessage(new StreamMessage("msg-1", Map.of("document_id", "doc-1")));

        assertThat(fixture.queue.acked).containsExactly("msg-1");
        assertThat(fixture.outbox.successes).isEmpty();
    }

    @Test
    @DisplayName("合法消息：直接处理并 ACK")
    void validMessageProcessesAndAcks() {
        Fixture fixture = fixture();

        fixture.consumer.processSingleMessage(
                new StreamMessage("msg-1", Map.of("task_id", "task-1", "document_id", "doc-1")));

        assertThat(fixture.indexing.ingested).hasSize(1);
        assertThat(fixture.outbox.successes).containsExactly("task-1");
        assertThat(fixture.queue.acked).containsExactly("msg-1");
    }

    @Test
    @DisplayName("业务失败：落库后正常返回 → ACK（重试走 publisher 重投）")
    void businessFailureCommitsAndAcks() {
        Fixture fixture = fixture(new FakeIndexingService(5, new IllegalStateException("embedding down")));
        fixture.outbox.entry = entry(POLICY.maxAttempts() - 2);

        fixture.consumer.processSingleMessage(
                new StreamMessage("msg-1", Map.of("task_id", "task-1", "document_id", "doc-1")));

        assertThat(fixture.outbox.recordedFailures).containsExactly("task-1");
        assertThat(fixture.queue.acked).containsExactly("msg-1");
    }

    @Test
    @DisplayName("提交失败：不 ACK，留待认领重投")
    void commitFailureDoesNotAck() {
        Fixture fixture = fixture();
        fixture.transactions.failOnCommit = new IllegalStateException("db gone");

        fixture.consumer.processSingleMessage(
                new StreamMessage("msg-1", Map.of("task_id", "task-1", "document_id", "doc-1")));

        assertThat(fixture.queue.acked).isEmpty();
    }

    // ---- 孤儿认领 ----

    @Test
    @DisplayName("认领孤儿失败：非致命，不抛")
    void claimOrphansFailureIsNonFatal() {
        Fixture fixture = fixture();
        fixture.queue.claimError = new IllegalStateException("redis down");

        fixture.consumer.claimAndProcessOrphans(); // 不应抛异常
    }

    @Test
    @DisplayName("认领到的孤儿走正常处理路径")
    void claimedOrphansAreProcessed() {
        Fixture fixture = fixture();
        fixture.documents.document = null;
        fixture.queue.claimed = List.of(
                new StreamMessage("msg-9", Map.of("task_id", "task-9", "document_id", "doc-9")));

        fixture.consumer.claimAndProcessOrphans();

        assertThat(fixture.outbox.successes).containsExactly("task-9");
        assertThat(fixture.queue.acked).containsExactly("msg-9");
    }
}
