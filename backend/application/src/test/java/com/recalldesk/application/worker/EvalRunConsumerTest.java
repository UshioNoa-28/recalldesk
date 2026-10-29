package com.recalldesk.application.worker;

import static org.assertj.core.api.Assertions.assertThat;

import com.recalldesk.application.FakeTransactionManager;
import com.recalldesk.application.eval.EvalMetrics;
import com.recalldesk.application.search.dto.SearchOutcome;
import com.recalldesk.application.search.SearchService;
import com.recalldesk.application.worker.PortStubs.FakeEvalRunTaskQueue;
import com.recalldesk.application.worker.PortStubs.StubEvalRepository;
import com.recalldesk.application.worker.PortStubs.StubEvalRunRepository;
import com.recalldesk.application.worker.PortStubs.StubEvalRunTaskRepository;
import com.recalldesk.domain.eval.EvalRun;
import com.recalldesk.domain.eval.EvalRunConfig;
import com.recalldesk.domain.eval.EvalRunItem;
import com.recalldesk.domain.eval.EvalRunStatus;
import com.recalldesk.domain.eval.EvalRunTask;
import com.recalldesk.domain.eval.EvalTaskStatus;
import com.recalldesk.domain.eval.EvalTestSetItem;
import com.recalldesk.domain.eval.EvidenceQuote;
import com.recalldesk.domain.retrieval.ChannelTrace;
import com.recalldesk.domain.retrieval.ChunkHit;
import com.recalldesk.domain.retrieval.FusionConfig;
import com.recalldesk.application.search.FusionSpec;
import com.recalldesk.application.search.dto.SearchProfile;
import com.recalldesk.domain.task.StreamMessage;
import com.recalldesk.domain.task.TaskPolicy;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * EvalRunConsumer 单元测试（全 fake，不连 PG / Redis）：
 * {@code tests/test_eval_run_consumer.py} 逐条对应。
 *
 * 一题消息的形状：领取校验 -> 一次检索 -> 回写结果 + 标任务 + 数着收尾。
 * 打磨的是收尾口径：只有「该 run 无在途任务」才 finalize，失败题也不例外。
 */
class EvalRunConsumerTest {

    private static final TaskPolicy POLICY =
            new TaskPolicy("anna_rag_eval_run_tasks", "anna_rag_eval_run_workers", 1.0, 50, 3, 10.0);
    private static final Instant NOW = Instant.parse("2026-09-12T00:00:00Z");
    private static final String QUERY = "豆腐有多少蛋白质？";
    /** run 的归属：检索视野由它决定，不是由消息里谁的 token 决定。 */
    private static final String USER = "user-alice";

    private static final ChunkHit HIT = new ChunkHit("doc-1", "notes.md", 2, 1, "豆腐的蛋白质含量", 0.9);

    private static EvalRunTask task(EvalTaskStatus status, int attempts) {
        return new EvalRunTask("task-1", "run-1", "item-1", status, attempts, null, NOW, NOW);
    }

    /** run 的配方：默认形态不带 fusion 键，走装配默认。 */
    private static EvalRun run(EvalRunStatus status, FusionConfig fusion) {
        return new EvalRun(
                "run-1", USER, "ts-1", status, new EvalRunConfig(5, false, true, fusion),
                null, null, NOW, null, 0, 1);
    }

    /** 一个金标块，坐标与 HIT 对齐：判分只看命中有没有落在这一块上。 */
    private static EvalTestSetItem item(String query) {
        return new EvalTestSetItem("item-1", query,
                List.of(new EvidenceQuote("ev-1", "item-1", "doc-1", 2, 0)));
    }

    /** 假检索服务：SearchService 是具体类，只覆写四参 search。 */
    private static final class FakeSearchService extends SearchService {

        private final RuntimeException error;
        final List<List<Object>> calls = new ArrayList<>();

        FakeSearchService() {
            this(null);
        }

        FakeSearchService(RuntimeException error) {
            super(null, null, null, null, 0, 0, null);
            this.error = error;
        }

        @Override
        public SearchOutcome search(String query, Integer topK, SearchProfile profile, String userId) {
            calls.add(List.of(query, topK, profile, userId));
            if (error != null) {
                throw error;
            }
            return new SearchOutcome(
                    List.of(HIT),
                    List.of(
                            new ChannelTrace("dense_original", query, List.of(HIT), 12),
                            new ChannelTrace("sparse", query, List.of(), 5)));
        }
    }

    /** 用例脚手架：共享状态挂在这里，消费者每个事务都复用同一批假件。 */
    private static final class Fixture {

        final FakeTransactionManager transactions = new FakeTransactionManager();
        final StubEvalRunTaskRepository runTasks = new StubEvalRunTaskRepository();
        final StubEvalRunRepository runs = new StubEvalRunRepository();
        final StubEvalRepository catalog = new StubEvalRepository();
        final FakeEvalRunTaskQueue queue = new FakeEvalRunTaskQueue();
        final FakeSearchService search;
        final EvalRunConsumer consumer;

        Fixture(FakeSearchService search) {
            this.search = search;
            this.runTasks.task = task(EvalTaskStatus.PENDING, 0);
            this.runs.run = run(EvalRunStatus.RUNNING, null);
            this.catalog.item = item(QUERY);
            this.consumer = new EvalRunConsumer(
                    queue, transactions.unitOfWork(), POLICY, runTasks, runs, catalog, search, "test-consumer");
        }
    }

    private static Fixture fixture() {
        return new Fixture(new FakeSearchService());
    }

    private static Fixture fixture(FakeSearchService search) {
        return new Fixture(search);
    }

    private static Map<String, String> ids() {
        return Map.of("task_id", "task-1", "run_id", "run-1", "item_id", "item-1");
    }

    // ---- 处理任务本体 ----

    @Test
    @DisplayName("正常路径：检索一次、落一行结果、标任务、数着收尾")
    void happyPathScoresFinalizesAndCommits() {
        Fixture fixture = fixture();

        fixture.consumer.handleTask(ids());

        // 检索一次：题面 + run 配方里的 k 与各档位（消融口径就在这一行）+ run 归属的检索视野
        // config 不带 fusion → 走装配默认（RRF k=60）
        assertThat(fixture.search.calls).containsExactly(
                List.of(QUERY, 5, new SearchProfile(false, true, FusionSpec.defaults()), USER));
        assertThat(fixture.runs.recorded).hasSize(1);
        EvalRunItem result = fixture.runs.recorded.getFirst();
        assertThat(result.testsetItemId()).isEqualTo("item-1");
        assertThat(result.hitRank()).isEqualTo(1); // 期望切片就是第一条命中
        assertThat(EvalMetrics.jointHit(result)).isEqualTo(1); // 块级全在
        // 节点评估轨迹：两路 + union oracle（sparse 空手，union 取 dense 的最优名次）
        assertThat(result.channels())
                .extracting(channel -> channel.kind(), channel -> channel.ranks())
                .containsExactly(
                        org.assertj.core.groups.Tuple.tuple("dense_original", List.of(1)),
                        org.assertj.core.groups.Tuple.tuple("sparse", List.of()),
                        org.assertj.core.groups.Tuple.tuple("union", List.of(1)));
        assertThat(result.latencyMs()).isGreaterThanOrEqualTo(0.0);
        assertThat(fixture.runTasks.successes).containsExactly("task-1");
        // 收尾：无在途无失败 -> DONE
        assertThat(fixture.runs.finalized).containsExactly(List.of("done", "-"));
        // 领取段与回写段各一次事务提交（模板包住只读段，它自己也会提交一个空事务）
        assertThat(fixture.transactions.commits).isEqualTo(2);
    }

    @Test
    @DisplayName("run 落库的融合配方原样进入这次检索的档位（不看装配默认）")
    void runConfigFusionRecipeReachesTheSearchProfile() {
        FusionConfig recipe = new FusionSpec("weighted", 60, "zscore", Map.of("dense", 1.0, "sparse", 2.0)).toConfig();
        Fixture fixture = fixture();
        fixture.runs.run = run(EvalRunStatus.RUNNING, recipe);

        fixture.consumer.handleTask(ids());

        assertThat(fixture.search.calls).containsExactly(
                List.of(QUERY, 5, new SearchProfile(false, true, FusionSpec.fromConfig(recipe)), USER));
    }

    @Test
    @DisplayName("任务行没了：仍试一次收尾，在途清零时 run 不会永远挂着")
    void missingTaskStillTriesToSettleTheRun() {
        Fixture fixture = fixture();
        fixture.runTasks.task = null;

        fixture.consumer.handleTask(ids());

        assertThat(fixture.runs.finalized).containsExactly(List.of("done", "-"));
        assertThat(fixture.runs.recorded).isEmpty();
    }

    @Test
    @DisplayName("任务已终态：跳过（redelivery 幂等），不再检索也不再收尾")
    void terminalTaskIsSkipped() {
        Fixture fixture = fixture();
        fixture.runTasks.task = task(EvalTaskStatus.SUCCESS, 0);

        fixture.consumer.handleTask(ids());

        assertThat(fixture.runTasks.successes).isEmpty();
        assertThat(fixture.runs.finalized).isEmpty();
        assertThat(fixture.search.calls).isEmpty();
    }

    @Test
    @DisplayName("run 已结束：消息算消费掉，不检索")
    void finishedRunConsumesTaskWithoutSearching() {
        Fixture fixture = fixture();
        fixture.runs.run = run(EvalRunStatus.DONE, null);

        fixture.consumer.handleTask(ids());

        assertThat(fixture.runTasks.successes).containsExactly("task-1");
        assertThat(fixture.runs.recorded).isEmpty();
        assertThat(fixture.search.calls).isEmpty();
    }

    @Test
    @DisplayName("run 不见了：同样算消费掉")
    void vanishedRunConsumesTaskWithoutSearching() {
        Fixture fixture = fixture();
        fixture.runs.run = null;

        fixture.consumer.handleTask(ids());

        assertThat(fixture.runTasks.successes).containsExactly("task-1");
        assertThat(fixture.runs.finalized).isEmpty();
    }

    @Test
    @DisplayName("结果行已在：补记 + 收尾，不再重复检索")
    void existingResultShortCircuitsWithoutSecondSearch() {
        Fixture fixture = fixture();
        fixture.runs.hasResult = true;

        fixture.consumer.handleTask(ids());

        assertThat(fixture.runTasks.successes).containsExactly("task-1");
        assertThat(fixture.runs.recorded).isEmpty();
        assertThat(fixture.runs.finalized).containsExactly(List.of("done", "-"));
        assertThat(fixture.search.calls).isEmpty();
    }

    @Test
    @DisplayName("题目没有题面：永久失败，标任务 FAILED 并收尾")
    void questionWithoutQueryFailsPermanently() {
        Fixture fixture = fixture();
        fixture.catalog.item = item(null);
        fixture.runTasks.counts = Map.of("failed", 1); // 模拟「该任务刚被标 failed」后的全局状态

        fixture.consumer.handleTask(ids());

        assertThat(fixture.runs.recorded).isEmpty();
        assertThat(fixture.runTasks.recordedFailures).containsExactly("task-1");
        assertThat(fixture.runTasks.failedEntries).containsExactly("task-1");
        assertThat(fixture.runs.finalized).containsExactly(List.of("failed", "1 道题评测失败"));
    }

    @Test
    @DisplayName("检索失败未超限：任务回 PENDING，不收尾")
    void searchFailureBelowMaxRetriesWithoutFinalize() {
        Fixture fixture = fixture(new FakeSearchService(new IllegalStateException("index down")));
        fixture.runTasks.task = task(EvalTaskStatus.PENDING, 1);

        fixture.consumer.handleTask(ids());

        assertThat(fixture.runTasks.recordedFailures).containsExactly("task-1");
        assertThat(fixture.runTasks.failedEntries).isEmpty();
        assertThat(fixture.runs.finalized).isEmpty();
    }

    @Test
    @DisplayName("检索失败到上限：标 FAILED 并收尾 run（否则永远 running）")
    void searchFailureAtMaxFailsTaskAndSettlesRun() {
        Fixture fixture = fixture(new FakeSearchService(new IllegalStateException("index down")));
        fixture.runTasks.task = task(EvalTaskStatus.PENDING, POLICY.maxAttempts());
        fixture.runTasks.counts = Map.of("success", 0, "failed", 1);

        fixture.consumer.handleTask(ids());

        assertThat(fixture.runTasks.failedEntries).containsExactly("task-1");
        assertThat(fixture.runs.finalized).containsExactly(List.of("failed", "1 道题评测失败"));
    }

    // ---- 消息层：字段校验与 ACK 规则 ----

    @Test
    @DisplayName("正常处理：ACK")
    void successfulHandlingAcks() {
        Fixture fixture = fixture();

        fixture.consumer.processSingleMessage(
                new StreamMessage("1-0", Map.of("task_id", "task-1", "run_id", "run-1", "item_id", "item-1")));

        assertThat(fixture.queue.acked).containsExactly("1-0");
    }

    @Test
    @DisplayName("缺 run_id：直接 ACK 掉")
    void messageWithoutFieldsIsAckedAway() {
        Fixture fixture = fixture();

        fixture.consumer.processSingleMessage(new StreamMessage("2-0", Map.of("task_id", "task-1")));

        assertThat(fixture.queue.acked).containsExactly("2-0");
    }

    @Test
    @DisplayName("提交失败：不 ACK，留待认领重投")
    void commitFailureLeavesMessageUnacked() {
        Fixture fixture = fixture();
        fixture.transactions.failOnCommit = new IllegalStateException("db gone");

        fixture.consumer.processSingleMessage(
                new StreamMessage("3-0", Map.of("task_id", "task-1", "run_id", "run-1", "item_id", "item-1")));

        assertThat(fixture.queue.acked).isEmpty();
    }

    @Test
    @DisplayName("退出信号已置位：run 只建组就走，不读消息")
    void runStopsImmediatelyWhenStopSignalSet() {
        // 消费者与 publisher 不同：进循环前必须先 ensureConsumerGroup，所以这里给真假件
        FakeEvalRunTaskQueue queue = new FakeEvalRunTaskQueue();

        new EvalRunConsumer(queue, null, POLICY, null, null, null, null).run(new CountDownLatch(0));

        assertThat(queue.acked).isEmpty();
    }
}
