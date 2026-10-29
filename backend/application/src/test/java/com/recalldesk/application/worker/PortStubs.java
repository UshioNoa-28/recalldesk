package com.recalldesk.application.worker;

import com.recalldesk.domain.Page;
import com.recalldesk.domain.documents.Document;
import com.recalldesk.domain.documents.DocumentTask;
import com.recalldesk.domain.documents.DocumentTaskStatus;
import com.recalldesk.domain.eval.EvalRun;
import com.recalldesk.domain.eval.EvalRunConfig;
import com.recalldesk.domain.eval.EvalRunItem;
import com.recalldesk.domain.eval.EvalRunStatus;
import com.recalldesk.domain.eval.EvalRunTask;
import com.recalldesk.domain.eval.EvalTaskStatus;
import com.recalldesk.domain.eval.EvalTestSet;
import com.recalldesk.domain.eval.EvalTestSetItem;
import com.recalldesk.domain.port.persistence.DocumentFileStorage;
import com.recalldesk.domain.port.persistence.DocumentRepository;
import com.recalldesk.domain.port.persistence.DocumentTaskRepository;
import com.recalldesk.domain.port.persistence.EvalRepository;
import com.recalldesk.domain.port.persistence.EvalRunRepository;
import com.recalldesk.domain.port.persistence.EvalRunTaskRepository;
import com.recalldesk.domain.port.queue.DocumentTaskQueue;
import com.recalldesk.domain.port.queue.EvalRunTaskQueue;
import com.recalldesk.domain.task.StreamMessage;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * worker 测试公用的端口假件：默认每个方法都抛 {@link UnsupportedOperationException}，
 * 用例只覆写自己关心的那几个。
 *
 * 用假件而不是 Mockito，与仓库既有测试同风格：这里要钉的是"以什么姿势打到端口"
 * （投递了什么字段、ACK 了哪条、有没有多调一次检索），手写假件记录下来的调用序列
 * 比 verify 更好读；没覆写的方法一被调用就直接炸，也顺手守住了"不该走的分支"。
 */
final class PortStubs {

    private PortStubs() {}

    static UnsupportedOperationException unused() {
        return new UnsupportedOperationException("用例不该走到这个端口方法");
    }

    /** 文档索引队列：记录 ACK / 投递（含追踪 ID），可配置投递失败与孤儿认领结果。 */
    static class FakeDocumentTaskQueue implements DocumentTaskQueue {

        final List<List<String>> enqueued = new ArrayList<>();
        final List<String> acked = new ArrayList<>();
        List<StreamMessage> claimed = List.of();
        List<StreamMessage> newMessages = List.of();
        RuntimeException enqueueError;
        RuntimeException claimError;
        /** 组内未确认数（积压播报读它）；用例想报积压就把它摆上。 */
        long unacked;
        /** 播报读了几次积压：心跳节流是否生效就看这个数。 */
        int pendingChecks;

        @Override
        public String enqueue(String taskId, String documentId) {
            if (enqueueError != null) {
                throw enqueueError;
            }
            enqueued.add(Arrays.asList(taskId, documentId));
            return "1-0";
        }

        @Override
        public void ensureConsumerGroup() {}

        @Override
        public List<StreamMessage> readNew(String consumerName, int count, int blockMs) {
            return newMessages;
        }

        @Override
        public void ack(String messageId) {
            acked.add(messageId);
        }

        @Override
        public List<StreamMessage> claimOrphans(String consumerName, int count) {
            if (claimError != null) {
                throw claimError;
            }
            return claimed;
        }

        @Override
        public long pendingCount() {
            pendingChecks++;
            return unacked;
        }
    }

    /** 逐题评测队列：同形（四个字段）。 */
    static class FakeEvalRunTaskQueue implements EvalRunTaskQueue {

        final List<List<String>> enqueued = new ArrayList<>();
        final List<String> acked = new ArrayList<>();
        List<StreamMessage> claimed = List.of();
        List<StreamMessage> newMessages = List.of();
        RuntimeException enqueueError;
        RuntimeException claimError;
        /** 组内未确认数（积压播报读它）。 */
        long unacked;
        /** 播报读了几次积压。 */
        int pendingChecks;

        @Override
        public String enqueue(String taskId, String runId, String itemId) {
            if (enqueueError != null) {
                throw enqueueError;
            }
            enqueued.add(Arrays.asList(taskId, runId, itemId));
            return "1-0";
        }

        @Override
        public void ensureConsumerGroup() {}

        @Override
        public List<StreamMessage> readNew(String consumerName, int count, int blockMs) {
            return newMessages;
        }

        @Override
        public void ack(String messageId) {
            acked.add(messageId);
        }

        @Override
        public List<StreamMessage> claimOrphans(String consumerName, int count) {
            if (claimError != null) {
                throw claimError;
            }
            return claimed;
        }

        @Override
        public long pendingCount() {
            pendingChecks++;
            return unacked;
        }
    }

    /** 文档元数据仓储：记录 update 的内容（状态流转靠它断言）。 */
    static class StubDocumentRepository implements DocumentRepository {

        Document document;
        final List<Document> updated = new ArrayList<>();

        @Override
        public void add(Document document) {
            throw unused();
        }

        @Override
        public Optional<Document> get(String documentId) {
            return document == null || !document.id().equals(documentId) ? Optional.empty() : Optional.of(document);
        }

        @Override
        public Optional<Document> getOwned(String userId, String documentId) {
            return get(documentId).filter(doc -> doc.userId().equals(userId));
        }

        @Override
        public Page<Document> list(String userId, int page, int pageSize) {
            throw unused();
        }

        @Override
        public void update(Document document) {
            updated.add(document);
        }

        @Override
        public boolean delete(String userId, String documentId) {
            throw unused();
        }
    }

    /** 文档任务发件箱：记录终态与失败重试；pending 由用例摆。 */
    static class StubDocumentTaskRepository implements DocumentTaskRepository {

        List<DocumentTask> pending = List.of();
        DocumentTask entry;
        final List<String> queued = new ArrayList<>();
        final List<String> successes = new ArrayList<>();
        final List<String> failedEntries = new ArrayList<>();
        final List<String> recordedFailures = new ArrayList<>();

        @Override
        public void add(String documentId) {
            throw unused();
        }

        @Override
        public Optional<DocumentTask> get(String entryId) {
            return Optional.ofNullable(entry);
        }

        @Override
        public List<DocumentTask> listPending(int limit) {
            return pending;
        }

        @Override
        public void markQueued(String entryId) {
            queued.add(entryId);
        }

        @Override
        public void markSuccess(String entryId) {
            successes.add(entryId);
        }

        @Override
        public void recordFailure(String entryId, String error) {
            recordedFailures.add(entryId);
            // 与真仓储同语义：attempts+1、状态回 PENDING，消费者紧接着 get 回来判断是否超限
            if (entry != null && entry.id().equals(entryId)) {
                entry = new DocumentTask(
                        entry.id(), entry.documentId(), DocumentTaskStatus.PENDING,
                        entry.attempts() + 1, error, entry.createdAt(), entry.queuedAt());
            }
        }

        @Override
        public void markFailed(String entryId) {
            failedEntries.add(entryId);
        }
    }

    /** 逐题评测任务发件箱：countByStatus 由用例摆，收尾口径全靠它。 */
    static class StubEvalRunTaskRepository implements EvalRunTaskRepository {

        List<EvalRunTask> pending = List.of();
        EvalRunTask task;
        Map<String, Integer> counts = Map.of("success", 1);
        final List<String> queued = new ArrayList<>();
        final List<String> successes = new ArrayList<>();
        final List<String> failedEntries = new ArrayList<>();
        final List<String> recordedFailures = new ArrayList<>();

        @Override
        public void add(String runId, String itemId) {
            throw unused();
        }

        @Override
        public Optional<EvalRunTask> get(String taskId) {
            return Optional.ofNullable(task);
        }

        @Override
        public List<EvalRunTask> listPending(int limit) {
            return pending;
        }

        @Override
        public void markQueued(String taskId) {
            queued.add(taskId);
        }

        @Override
        public void markSuccess(String taskId) {
            successes.add(taskId);
        }

        @Override
        public void recordFailure(String taskId, String error) {
            recordedFailures.add(taskId);
            // 与真仓储同语义：attempts+1、状态回 PENDING（消费者随后 get 回来判超限）
            if (task != null && task.id().equals(taskId)) {
                task = new EvalRunTask(
                        task.id(), task.runId(), task.itemId(), EvalTaskStatus.PENDING,
                        task.attempts() + 1, error, task.createdAt(), task.queuedAt());
            }
        }

        @Override
        public void markFailed(String taskId) {
            failedEntries.add(taskId);
        }

        @Override
        public int resetFailedForRun(String runId) {
            throw unused();
        }

        @Override
        public Map<String, Integer> countByStatus(String runId) {
            return counts;
        }
    }

    /** 评测集 / 题目侧。 */
    static class StubEvalRepository implements EvalRepository {

        EvalTestSetItem item;
        EvalTestSet testSet;
        final List<List<Integer>> evidenceUpdates = new ArrayList<>();
        final List<List<EvalTestSetItem>> addedItems = new ArrayList<>();

        @Override
        public void createTestSet(String testSetId, String userId, String name) {
            throw unused();
        }

        @Override
        public Optional<EvalTestSet> getTestSet(String userId, String testSetId) {
            return testSet == null || !testSet.id().equals(testSetId) || !testSet.userId().equals(userId)
                    ? Optional.empty()
                    : Optional.of(testSet);
        }

        @Override
        public List<EvalTestSet> listTestSets(String userId) {
            throw unused();
        }

        @Override
        public void deleteTestSet(String userId, String testSetId) {
            throw unused();
        }

        @Override
        public void addItems(String testSetId, List<EvalTestSetItem> items) {
            addedItems.add(items);
        }

        @Override
        public List<EvalTestSetItem> listTestSetItems(String testSetId) {
            throw unused();
        }

        @Override
        public Optional<EvalTestSetItem> getItem(String itemId) {
            return item == null || !item.id().equals(itemId) ? Optional.empty() : Optional.of(item);
        }

        @Override
        public int deleteItemsReferencingDocument(String documentId) {
            throw unused();
        }

    }

    /** run 侧。 */
    static class StubEvalRunRepository implements EvalRunRepository {

        EvalRun run;
        List<EvalRunItem> items = List.of();
        boolean hasResult;
        final List<EvalRunItem> recorded = new ArrayList<>();
        /** finishRun 的调用记录：status + errorMessage（无错误记 "-"）。 */
        final List<List<String>> finalized = new ArrayList<>();

        @Override
        public void createRun(String runId, String userId, String testsetId, EvalRunConfig config) {
            throw unused();
        }

        @Override
        public void recordRunItem(String runId, EvalRunItem result) {
            recorded.add(result);
        }

        @Override
        public Optional<EvalRun> getRun(String runId) {
            return Optional.ofNullable(run);
        }

        @Override
        public Optional<EvalRun> getRunOwned(String userId, String runId) {
            return getRun(runId).filter(row -> row.userId().equals(userId));
        }

        @Override
        public List<EvalRunItem> listRunItems(String runId) {
            return items;
        }

        @Override
        public List<EvalRun> listRuns(String userId, String testsetId) {
            throw unused();
        }

        @Override
        public boolean hasRunResult(String runId, String testsetItemId) {
            return hasResult;
        }

        @Override
        public int deleteRunsReferencingDocument(String documentId) {
            throw unused();
        }

        @Override
        public void finishRun(String runId, EvalRunStatus status, Map<String, Object> metrics, String errorMessage) {
            finalized.add(List.of(status.wire(), errorMessage == null ? "-" : errorMessage));
        }

        @Override
        public void reopenRun(String runId) {
            throw unused();
        }
    }

    /** 原始文件读取：只认 read。 */
    static class StubFileStorage implements DocumentFileStorage {

        byte[] content = "文件内容".getBytes(java.nio.charset.StandardCharsets.UTF_8);
        RuntimeException readError;

        @Override
        public String save(String documentId, byte[] content) {
            throw unused();
        }

        @Override
        public byte[] read(String storageKey) {
            if (readError != null) {
                throw readError;
            }
            return content;
        }

        @Override
        public void delete(String storageKey) {
            throw unused();
        }
    }
}
