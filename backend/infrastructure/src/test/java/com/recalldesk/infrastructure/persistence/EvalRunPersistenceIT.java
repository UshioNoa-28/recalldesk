package com.recalldesk.infrastructure.persistence;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.recalldesk.domain.eval.ChannelScore;
import com.recalldesk.domain.eval.EvalRun;
import com.recalldesk.domain.eval.EvalRunConfig;
import com.recalldesk.domain.eval.EvalRunItem;
import com.recalldesk.domain.eval.EvalRunStatus;
import com.recalldesk.domain.eval.EvalRunTask;
import com.recalldesk.domain.eval.EvalTaskStatus;
import com.recalldesk.domain.eval.EvalTestSetItem;
import com.recalldesk.domain.eval.EvidenceQuote;
import com.recalldesk.domain.port.persistence.EvalRepository;
import com.recalldesk.domain.port.persistence.EvalRunRepository;
import com.recalldesk.domain.port.persistence.EvalRunTaskRepository;
import com.recalldesk.domain.retrieval.FusionConfig;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.autoconfigure.EnableAutoConfiguration;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Import;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ContextConfiguration;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * run 侧四张表的真库用例（手动拉起：{@code -Dtest=EvalRunPersistenceIT}）。
 *
 * 单测替我不了的都在这里：jsonb 列绑参（PG 对 varchar 表达式直接拒收，必须显式 CAST）、
 * 写进去再读出来的键名与数值是否还是那份口径、部分唯一索引兜住的"一个集同时只有一个 running"、
 * 以及条件写真的能把重复收尾变成空操作。整体回滚，库里那份语料删不起。
 */
@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.NONE,
        properties = {
            "spring.datasource.url=jdbc:postgresql://127.0.0.1:5435/anna_rag",
            "spring.datasource.username=rag",
            "spring.datasource.password=rag",
            "spring.datasource.driver-class-name=org.postgresql.Driver",
            "mybatis-plus.configuration.map-underscore-to-camel-case=true",
            "recalldesk.eval-run-task.retry-backoff-base-seconds=10",
        })
@Transactional
@ContextConfiguration(classes = EvalRunPersistenceIT.TestApp.class)
class EvalRunPersistenceIT {

    @Configuration(proxyBeanMethods = false)
    @EnableAutoConfiguration
    @Import({MyBatisEvalRepository.class, MyBatisEvalRunRepository.class, MyBatisEvalRunTaskRepository.class})
    static class TestApp {}

    @Autowired
    private EvalRepository evals;

    @Autowired
    private EvalRunRepository runs;

    @Autowired
    private EvalRunTaskRepository runTasks;

    @Autowired
    private JdbcTemplate jdbc;

    @Autowired
    private PlatformTransactionManager transactionManager;

    @Test
    void runConfigRoundTripsThroughJsonbAndProgressIsDerivedFromResultRows() {
        String alice = seedUser();
        String testSetId = newTestSetWithTwoQuestions(alice);
        String runId = UUID.randomUUID().toString();
        EvalRunConfig config = new EvalRunConfig(5, true, false,
                new FusionConfig("weighted", 30, "zscore", Map.of("dense", 0.7, "sparse", 2.5)));

        runs.createRun(runId, alice, testSetId, config);
        EvalRun created = runs.getRun(runId).orElseThrow();
        assertThat(created.status()).isEqualTo(EvalRunStatus.RUNNING);
        assertThat(created.testsetId()).isEqualTo(testSetId);
        assertThat(created.userId()).isEqualTo(alice);
        assertThat(created.createdAt()).isNotNull();
        assertThat(created.finishedAt()).isNull();
        assertThat(created.metrics()).isNull();
        // config 是快照：嵌套的 fusion 也要按线上形状原样回来（键名走 snake_case）
        assertThat(created.config()).usingRecursiveComparison().isEqualTo(config);
        assertThat(created.progressDone()).isZero();
        assertThat(created.progressTotal()).isEqualTo(2); // 集里的题数

        // 逐题结果的 evidence_total 数的是引文段数，不是块数
        List<String> questionIds = questionIds(testSetId);
        // partial：该 2 段只捞回 1 段（joint 0、coverage 给部分分）；exact：单跳正中第 1 名
        EvalRunItem partial = scored(questionIds.get(0), 2, List.of(2), 10.0,
                List.of(channel("dense_original", "原句", List.of(2)), channel("union", null, List.of(2))));
        EvalRunItem exact = scored(questionIds.get(1), 1, List.of(1), 30.0, List.of());
        runs.recordRunItem(runId, partial);
        runs.recordRunItem(runId, exact);

        assertThat(runs.getRun(runId).orElseThrow().progressDone()).isEqualTo(2);
        assertThat(runs.hasRunResult(runId, questionIds.get(0))).isTrue();
        assertThat(runs.hasRunResult(runId, "查不到就空")).isFalse();

        List<EvalRunItem> results = runs.listRunItems(runId);
        assertThat(results).hasSize(2);
        // 题面从题目表联查带出：结果表里没有副本
        assertThat(results).allSatisfy(item -> assertThat(item.query()).startsWith("题面 "));
        EvalRunItem multi = results.stream()
                .filter(item -> item.evidenceTotal() == 2).findFirst().orElseThrow();
        assertThat(multi.evidenceRanks()).containsExactly(2);
        assertThat(multi.hitRank()).isEqualTo(2);
        // 逐通道快照原样回来：union 行的 text 是 null，jsonb 里也得是 null 而不是缺键
        assertThat(multi.channels())
                .containsExactly(channel("dense_original", "原句", List.of(2)), channel("union", null, List.of(2)));
        EvalRunItem single = results.stream()
                .filter(item -> item.evidenceTotal() == 1).findFirst().orElseThrow();
        assertThat(single.channels()).isEmpty();

        // 收尾是应用层的事；这里只验证条件写：只有 running 能被写成终态
        runs.finishRun(runId, EvalRunStatus.DONE, Map.of("queries", 2, "recall@5", 0.5), null);
        EvalRun done = runs.getRun(runId).orElseThrow();
        assertThat(done.status()).isEqualTo(EvalRunStatus.DONE);
        assertThat(done.finishedAt()).isNotNull();
        // jsonb 原样回来：写进去什么就读出什么
        assertThat(done.metrics()).containsEntry("recall@5", 0.5).containsEntry("queries", 2);
        // 重复收尾 / 与启动扫相撞：条件写匹配不到行，finished_at 保持第一次那个值
        Instant firstFinishedAt = done.finishedAt();
        runs.finishRun(runId, EvalRunStatus.FAILED, null, "不该发生");
        EvalRun again = runs.getRun(runId).orElseThrow();
        assertThat(again.status()).isEqualTo(EvalRunStatus.DONE);
        assertThat(again.finishedAt()).isEqualTo(firstFinishedAt);
        // done 的 run 也重开不了：重开只对 failed 生效
        runs.reopenRun(runId);
        assertThat(runs.getRun(runId).orElseThrow().status()).isEqualTo(EvalRunStatus.DONE);
    }

    @Test
    void permanentFailuresFailTheRunAndReopenOnlyFromFailed() {
        String alice = seedUser();
        String bob = seedUser();
        String testSetId = newTestSetWithTwoQuestions(alice);
        String runId = UUID.randomUUID().toString();
        runs.createRun(runId, alice, testSetId, new EvalRunConfig(3, false, false, null));

        // 失败收尾：不写指标（决策在应用层，这里验证列行为）
        runs.finishRun(runId, EvalRunStatus.FAILED, null, "2 道题评测失败");
        EvalRun failed = runs.getRun(runId).orElseThrow();
        assertThat(failed.status()).isEqualTo(EvalRunStatus.FAILED);
        assertThat(failed.errorMessage()).isEqualTo("2 道题评测失败");
        assertThat(failed.metrics()).isNull();
        assertThat(failed.finishedAt()).isNotNull();

        runs.reopenRun(runId);
        EvalRun reopened = runs.getRun(runId).orElseThrow();
        assertThat(reopened.status()).isEqualTo(EvalRunStatus.RUNNING);
        assertThat(reopened.errorMessage()).isNull();
        assertThat(reopened.finishedAt()).isNull();

        // 归属过滤只在带 user 的那两个读法上：getRun 是 worker 用的，它没有调用方身份
        assertThat(runs.getRunOwned(alice, runId)).isPresent();
        assertThat(runs.getRunOwned(bob, runId)).isEmpty();
        assertThat(runs.listRuns(bob, testSetId)).isEmpty();

        // 「一个测试集同时最多一个 running」由部分唯一索引兜住（service 的先查再插有并发窗口）
        TransactionTemplate savepoint = new TransactionTemplate(Objects.requireNonNull(transactionManager));
        savepoint.setPropagationBehavior(TransactionDefinition.PROPAGATION_NESTED);
        assertThatThrownBy(() -> savepoint.execute(status -> {
            runs.createRun(UUID.randomUUID().toString(), alice, testSetId, new EvalRunConfig(3, false, false, null));
            return null;
        })).isInstanceOf(DataIntegrityViolationException.class);

        assertThat(runs.listRuns(alice, testSetId)).extracting(EvalRun::id).containsExactly(runId);
        assertThat(runs.listRuns(alice, "查不到就空")).isEmpty();
    }

    @Test
    void runResultsJoinBackTheirQuestionAndTasksWalkTheStateMachine() {
        String alice = seedUser();
        String testSetId = newTestSetWithTwoQuestions(alice);
        String runId = UUID.randomUUID().toString();
        runs.createRun(runId, alice, testSetId, new EvalRunConfig(5, true, true, null));
        List<String> questionIds = questionIds(testSetId);

        runs.recordRunItem(runId, scored(questionIds.get(0), 1, List.of(1), 5.0, List.of()));
        // 结果行的题面与引文坐标都是从现有表联查回来的，结果表里没有副本
        // 结果行的题面与引文坐标都是从现有表联查回来的，结果表里没有副本
        // （同事务写入的题目 created_at 相同，先后交给堆物理顺序，所以只断前缀不断是哪一题）
        EvalRunItem joined = runs.listRunItems(runId).getFirst();
        assertThat(joined.query()).startsWith("题面 ");
        assertThat(joined.evidenceTotal()).isEqualTo(1);

        // 逐题评测任务：一题一行，fan-out 与状态机
        runTasks.add(runId, questionIds.get(0));
        runTasks.add(runId, questionIds.get(1));
        String first = taskIdForItem(runId, questionIds.get(0));
        assertThat(runTasks.listPending(500)).extracting(EvalRunTask::id).contains(first);
        runTasks.markQueued(first);
        assertThat(runTasks.get(first).orElseThrow().status()).isEqualTo(EvalTaskStatus.QUEUE);
        runTasks.recordFailure(first, "模型超时");
        EvalRunTask retried = runTasks.get(first).orElseThrow();
        assertThat(retried.status()).isEqualTo(EvalTaskStatus.PENDING);
        assertThat(retried.attempts()).isEqualTo(1);
        // 这条链的基数是 10 秒（题多、单题便宜），不是文档链那份 30
        assertThat(retreatSeconds(first)).isBetween(5L, 15L);

        runTasks.markFailed(first);
        assertThat(runTasks.countByStatus(runId))
                .containsEntry(EvalTaskStatus.FAILED.wire(), 1)
                .containsEntry(EvalTaskStatus.PENDING.wire(), 1);
        assertThat(runTasks.resetFailedForRun(runId)).isEqualTo(1);
        assertThat(runTasks.countByStatus(runId)).containsEntry(EvalTaskStatus.PENDING.wire(), 2);
        assertThat(runTasks.resetFailedForRun(runId)).isZero(); // 没有 FAILED 可复位也是合法结果

        // 删 run 连结果行和任务行一起 CASCADE 带走
        jdbc.update("DELETE FROM eval_runs WHERE id = ?", runId);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM eval_run_items WHERE run_id = ?",
                Integer.class, runId)).isZero();
        assertThat(jdbc.queryForObject("SELECT count(*) FROM eval_run_tasks WHERE run_id = ?",
                Integer.class, runId)).isZero();
    }

    private static EvalRunItem scored(
            String itemId, int total, List<Integer> ranks, double latencyMs, List<ChannelScore> channels) {
        return new EvalRunItem(itemId, null, ranks.isEmpty() ? null : ranks.get(0), latencyMs,
                total, ranks.size(), ranks, channels);
    }

    private static ChannelScore channel(String kind, String text, List<Integer> ranks) {
        return new ChannelScore(kind, text, ranks, 12L);
    }

    private static EvalTestSetItem item(String id, String query, EvidenceQuote... evidence) {
        return new EvalTestSetItem(id, query, List.of(evidence));
    }

    private static EvidenceQuote quote(String id, String documentId, int ordinal) {
        return new EvidenceQuote(id, "item", documentId, ordinal, ordinal);
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> buckets(Map<String, Object> metrics, String key) {
        Object value = metrics.get(key);
        assertThat(value).isInstanceOf(Map.class);
        return (Map<String, Object>) value;
    }

    /** 两道题（一题一段引文、一题两段），返回集 id。 */
    private String newTestSetWithTwoQuestions(String userId) {
        String testSetId = UUID.randomUUID().toString();
        String documentId = seedDocument(userId);
        evals.createTestSet(testSetId, userId, "it-run");
        evals.addItems(testSetId, List.of(
                item(UUID.randomUUID().toString(), "题面 0",
                        quote(UUID.randomUUID().toString(), documentId, 0)),
                item(UUID.randomUUID().toString(), "题面 1",
                        quote(UUID.randomUUID().toString(), documentId, 0),
                        quote(UUID.randomUUID().toString(), documentId, 1))));
        return testSetId;
    }

    private List<String> questionIds(String testSetId) {
        return evals.listTestSetItems(testSetId).stream().map(EvalTestSetItem::id).toList();
    }

    private String taskIdForItem(String runId, String itemId) {
        return jdbc.queryForObject(
                "SELECT id FROM eval_run_tasks WHERE run_id = ? AND item_id = ?",
                String.class, runId, itemId);
    }

    private long retreatSeconds(String taskId) {
        Instant at = jdbc.queryForObject(
                "SELECT next_retry_at FROM eval_run_tasks WHERE id = ?", Instant.class, taskId);
        return Duration.between(Instant.now(), at).getSeconds();
    }

    private String seedUser() {
        String id = UUID.randomUUID().toString();
        jdbc.update("INSERT INTO users (id, username, password_hash) VALUES (?, ?, ?)",
                id, "it-" + id, "pbkdf2$it-placeholder");
        return id;
    }

    private String seedDocument(String userId) {
        String id = UUID.randomUUID().toString();
        jdbc.update(
                "INSERT INTO documents (id, user_id, name, storage_key, size_bytes, status) "
                        + "VALUES (?, ?, ?, ?, ?, 'pending')",
                id, userId, "it-run.txt", "it/" + id, 1L);
        return id;
    }
}
