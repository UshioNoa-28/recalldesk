package com.recalldesk.application.eval;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.recalldesk.application.FakeTransactionManager;
import com.recalldesk.domain.eval.ChannelScore;
import com.recalldesk.domain.eval.EvalRun;
import com.recalldesk.domain.eval.EvalRunConfig;
import com.recalldesk.application.eval.dto.EvalRunDetail;
import com.recalldesk.domain.eval.EvalRunItem;
import com.recalldesk.domain.eval.EvalRunStatus;
import com.recalldesk.domain.eval.EvalRunTask;
import com.recalldesk.domain.eval.EvalTestSet;
import com.recalldesk.domain.eval.EvalTestSetItem;
import com.recalldesk.domain.eval.EvidenceQuote;
import com.recalldesk.domain.exception.eval.RunNotFoundException;
import com.recalldesk.domain.exception.eval.TestSetNotFoundException;
import com.recalldesk.domain.port.persistence.ChunkIndex;
import com.recalldesk.domain.port.persistence.EvalRepository;
import com.recalldesk.domain.port.persistence.EvalRunRepository;
import com.recalldesk.domain.port.persistence.EvalRunTaskRepository;
import com.recalldesk.domain.retrieval.ChunkHit;
import com.recalldesk.domain.retrieval.ChunkRecord;
import com.recalldesk.domain.retrieval.FusionConfig;
import com.recalldesk.application.search.FusionSpec;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DuplicateKeyException;

/**
 * EvalRunService 用例测试（全 fake，不连 PG）。
 *
 * run 的「跑」在 consumer 那边测，这里只测开跑前的判断与读：什么不让跑
 * （集不存在、没题、已经有一次在跑、引文在文档里找不到了）、写进去的配方是什么、
 * 开跑时按题 fan-out 了几条评测任务。
 */
class EvalRunServiceTest {

    private static final Instant CREATED_AT = Instant.parse("2026-09-03T12:00:00Z");
    private static final String ALICE = "user-alice";
    private static final String BOB = "user-bob";
    /** 不给配方时的落库形状（装配默认）：写死在这里，改默认是一次有意的编辑。 */
    private static final FusionConfig DEFAULT_FUSION = FusionSpec.defaults().toConfig();

    private static final String TOFU = "豆腐的蛋白质含量约为八克";
    private static final String MILK = "牛奶的钙含量是每百克一百零四毫克";

    private static ChunkRecord chunk(String text) {
        return new ChunkRecord("doc-1", text.equals(TOFU) ? 0 : 1, text, "营养指南.txt", 2);
    }

    private static EvidenceQuote quote(String id, String documentId, int chunkIndex, int ordinal) {
        return new EvidenceQuote(id, "item-1", documentId, chunkIndex, ordinal);
    }

    /** 假件一身兼二职：testsets/items 侧与 run 侧共享同一份内存状态。 */
    private static class FakeEvalStore implements EvalRepository, EvalRunRepository {

        final Map<String, EvalTestSet> testSets = new LinkedHashMap<>();
        final List<EvalTestSetItem> items = new ArrayList<>();
        final Map<String, EvalRun> runs = new LinkedHashMap<>();
        final Map<String, List<EvalRunItem>> results = new LinkedHashMap<>();
        final List<EvalRunConfig> createdConfigs = new ArrayList<>();
        final List<String> createdRunIds = new ArrayList<>();
        /** 重解析写回的落点：evidenceId -> (块号, 可信度)。 */
        final Map<String, List<Integer>> evidenceUpdates = new LinkedHashMap<>();

        FakeEvalStore() {
            testSets.put("ts-1", new EvalTestSet("ts-1", ALICE, "水果题集", 2, CREATED_AT));
            items.add(item(0));
            items.add(item(1));
        }

        /** 题号就是块号：item-0 的金标在第 0 块，item-1 在第 1 块。 */
        static EvalTestSetItem item(int index) {
            return new EvalTestSetItem(
                    "item-" + index,
                    index == 0 ? "豆腐有多少蛋白质？" : "牛奶补钙吗？",
                    List.of(quote("ev-" + index, "doc-1", index, 0)));
        }

        /** run 行是不可变 record，摆布状态就整行换掉。 */
        void replaceRun(String runId, EvalRunStatus status) {
            EvalRun run = runs.get(runId);
            runs.put(runId, new EvalRun(run.id(), run.userId(), run.testsetId(), status, run.config(),
                    run.metrics(), null, run.createdAt(), null, run.progressDone(), run.progressTotal()));
        }

        @Override
        public Optional<EvalTestSet> getTestSet(String userId, String testSetId) {
            EvalTestSet testSet = testSets.get(testSetId);
            // 归属过滤在 SQL 的 WHERE 里，这里同形：不是你的就是不存在
            return testSet == null || !testSet.userId().equals(userId)
                    ? Optional.empty() : Optional.of(testSet);
        }

        @Override
        public List<EvalTestSetItem> listTestSetItems(String testSetId) {
            return "ts-1".equals(testSetId) ? items : List.of();
        }

        @Override
        public void createRun(String runId, String userId, String testSetId, EvalRunConfig config) {
            createdRunIds.add(runId);
            createdConfigs.add(config);
            runs.put(runId, new EvalRun(runId, userId, testSetId, EvalRunStatus.RUNNING, config, null, null,
                    CREATED_AT, null, 0, items.size()));
            results.put(runId, new ArrayList<>());
        }

        @Override
        public Optional<EvalRun> getRun(String runId) {
            EvalRun run = runs.get(runId);
            if (run == null) {
                return Optional.empty();
            }
            // 进度是数出来的，不是存的：done = 已有结果行，total = 题数
            EvalRun withProgress = new EvalRun(run.id(), run.userId(), run.testsetId(), run.status(),
                    run.config(), run.metrics(), run.errorMessage(), run.createdAt(), run.finishedAt(),
                    results.getOrDefault(runId, List.of()).size(), items.size());
            runs.put(runId, withProgress);
            return Optional.of(withProgress);
        }

        @Override
        public Optional<EvalRun> getRunOwned(String userId, String runId) {
            return getRun(runId).filter(run -> run.userId().equals(userId));
        }

        @Override
        public List<EvalRunItem> listRunItems(String runId) {
            return results.getOrDefault(runId, List.of());
        }

        @Override
        public List<EvalRun> listRuns(String userId, String testSetId) {
            return runs.values().stream()
                    .filter(run -> run.testsetId().equals(testSetId) && run.userId().equals(userId))
                    .toList();
        }

        @Override
        public void reopenRun(String runId) {
            EvalRun run = runs.get(runId);
            if (run != null && run.status() == EvalRunStatus.FAILED) {
                runs.put(runId, new EvalRun(run.id(), run.userId(), run.testsetId(), EvalRunStatus.RUNNING,
                        run.config(), run.metrics(), null, run.createdAt(), null,
                        run.progressDone(), run.progressTotal()));
            }
        }

        @Override
        public boolean hasRunResult(String runId, String testsetItemId) {
            return false;
        }

        @Override
        public int deleteRunsReferencingDocument(String documentId) {
            throw new UnsupportedOperationException();
        }

        @Override
        public void recordRunItem(String runId, EvalRunItem result) {
            results.computeIfAbsent(runId, key -> new ArrayList<>()).add(result);
        }

        @Override
        public void finishRun(String runId, EvalRunStatus status, Map<String, Object> metrics,
                String errorMessage) {}

        @Override
        public void createTestSet(String testSetId, String userId, String name) {
            throw new UnsupportedOperationException();
        }

        @Override
        public List<EvalTestSet> listTestSets(String userId) {
            throw new UnsupportedOperationException();
        }

        @Override
        public void deleteTestSet(String userId, String testSetId) {
            throw new UnsupportedOperationException();
        }

        @Override
        public void addItems(String testSetId, List<EvalTestSetItem> newItems) {
            throw new UnsupportedOperationException();
        }

        @Override
        public Optional<EvalTestSetItem> getItem(String itemId) {
            throw new UnsupportedOperationException();
        }

        @Override
        public int deleteItemsReferencingDocument(String documentId) {
            throw new UnsupportedOperationException();
        }
    }

    /** 索引侧只用到 getDocumentChunks：起跑前的重解析读它，读不到引文就是题面失效。 */
    private static class FakeChunkIndex implements ChunkIndex {

        final List<ChunkRecord> records = new ArrayList<>(List.of(chunk(TOFU), chunk(MILK)));

        @Override
        public List<ChunkRecord> getDocumentChunks(String documentId) {
            return records;
        }

        @Override
        public void insertChunks(
                String documentId, String userId, String documentName, List<String> chunks, List<double[]> vectors) {
            throw new UnsupportedOperationException();
        }

        @Override
        public List<ChunkHit> searchByDense(double[] denseVector, int topK, String userId) {
            throw new UnsupportedOperationException();
        }

        @Override
        public List<ChunkHit> searchBySparse(String queryText, int topK, String userId) {
            throw new UnsupportedOperationException();
        }

        @Override
        public Optional<ChunkRecord> getChunk(String documentId, int chunkIndex) {
            throw new UnsupportedOperationException();
        }

        @Override
        public void deleteDocument(String documentId) {
            throw new UnsupportedOperationException();
        }
    }

    /** fan-out 的落点：startRun 每题 add 一条 PENDING 任务。 */
    private static class FakeRunTaskRepository implements EvalRunTaskRepository {

        final List<String> added = new ArrayList<>();
        final Map<String, List<String>> failed = new LinkedHashMap<>();
        final List<String> reset = new ArrayList<>();

        @Override
        public void add(String runId, String itemId) {
            added.add(runId + ":" + itemId);
        }

        @Override
        public int resetFailedForRun(String runId) {
            List<String> ids = failed.remove(runId);
            if (ids == null || ids.isEmpty()) {
                return 0;
            }
            reset.add(runId);
            return ids.size();
        }

        @Override
        public Optional<EvalRunTask> get(String taskId) {
            return Optional.empty();
        }

        @Override
        public List<EvalRunTask> listPending(int limit) {
            return List.of();
        }

        @Override
        public void markQueued(String taskId) {}

        @Override
        public void markSuccess(String taskId) {}

        @Override
        public void recordFailure(String taskId, String error) {}

        @Override
        public void markFailed(String taskId) {}

        @Override
        public Map<String, Integer> countByStatus(String runId) {
            return Map.of();
        }
    }

    private static class Harness {

        final FakeEvalStore evals = new FakeEvalStore();
        final FakeRunTaskRepository runTasks = new FakeRunTaskRepository();
        final FakeChunkIndex index = new FakeChunkIndex();
        final FakeTransactionManager txManager = new FakeTransactionManager();
        final EvalRunService service;

        Harness() {
            this(5, null);
        }

        Harness(int defaultTopK, FusionSpec defaultFusion) {
            service = new EvalRunService(
                    evals, evals, runTasks, index, txManager.unitOfWork(), defaultTopK, defaultFusion);
        }

        EvalRunDetail start(String testSetId) {
            return service.startRun(ALICE, testSetId, null, true, true, null);
        }

        int commits() {
            return txManager.commits;
        }
    }

    private static EvalRunItem result(int index) {
        return new EvalRunItem("item-" + index, "豆腐有多少蛋白质？", index + 1, 10.0, 2, 1,
                List.of(index + 1), List.of());
    }

    @Test
    @DisplayName("开跑：写一行 running + 按题 fan-out 逐题任务，同一个提交")
    void createsRunningRunThenFansOutOneTaskPerQuestion() {
        Harness harness = new Harness();

        EvalRunDetail detail = harness.start("ts-1");

        String runId = detail.run().id();
        assertThat(harness.evals.createdRunIds).containsExactly(runId);
        assertThat(harness.evals.createdConfigs)
                .containsExactly(new EvalRunConfig(5, true, true, DEFAULT_FUSION));
        assertThat(harness.commits()).isEqualTo(1);
        // 两道题 -> 两条逐题任务，run 行与任务行同一个提交（发件箱的定义）
        assertThat(harness.runTasks.added).containsExactly(runId + ":item-0", runId + ":item-1");
        assertThat(detail.run().status()).isEqualTo(EvalRunStatus.RUNNING);
        assertThat(detail.run().userId()).isEqualTo(ALICE);
        assertThat(detail.run().progressDone()).isZero();
        assertThat(detail.run().progressTotal()).isEqualTo(2);
        assertThat(detail.items()).isEmpty();
        assertThat(detail.run().createdAt()).isEqualTo(CREATED_AT);
    }

    @Test
    @DisplayName("k、检索开关与融合档位都原样留在 run 的 config 上：消融全靠它")
    void recordsTheRouteRecipeOfThisRun() {
        Harness harness = new Harness();

        EvalRunDetail detail = harness.service.startRun(ALICE, "ts-1", 3, true, false, null);

        assertThat(detail.run().config())
                .isEqualTo(new EvalRunConfig(3, true, false, DEFAULT_FUSION));
    }

    @Test
    @DisplayName("请求只给想改的键，落库的是叠在装配默认之上的完整配方")
    void storesFusionRecipeResolvedAgainstAssemblyDefault() {
        // 半个 config 描述不了实验：事后看这一份要能一字不差说出它怎么合的
        Harness harness = new Harness(5,
                new FusionSpec("rrf", 40, "minmax", Map.of("dense", 1.0, "sparse", 1.0)));

        EvalRunDetail detail = harness.service.startRun(ALICE, "ts-1", null, true, true,
                new FusionConfig("weighted", null, null, Map.of("sparse", 2.0)));

        assertThat(detail.run().config().fusion()).isEqualTo(new FusionConfig(
                "weighted", 40, "minmax", Map.of("dense", 1.0, "sparse", 2.0))); // 权重按键合并
    }

    @Test
    @DisplayName("非法融合方法：构造档位时就抛，不落半个 run")
    void rejectsUnknownFusionMethod() {
        Harness harness = new Harness();

        assertThatThrownBy(() -> harness.service.startRun(ALICE, "ts-1", null, true, true,
                new FusionConfig("comb", null, null, Map.of())))
                .isInstanceOf(IllegalArgumentException.class);

        assertThat(harness.evals.createdRunIds).isEmpty();
    }

    @Test
    @DisplayName("请求没给 top_k 时吃装配默认")
    void defaultTopKAppliesWhenRequestOmitsIt() {
        Harness harness = new Harness(8, null);

        assertThat(harness.start("ts-1").run().config().topK()).isEqualTo(8);
    }

    @Test
    @DisplayName("一道题都没有：空评测给出的 recall@k = 0 是假数字")
    void testsetWithoutItemsCannotBeRun() {
        Harness harness = new Harness();
        harness.evals.items.clear();

        assertThatThrownBy(() -> harness.start("ts-1"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("还没有题目");

        assertThat(harness.commits()).isZero();
        assertThat(harness.runTasks.added).isEmpty();
    }

    @Test
    @DisplayName("分块变少、金标块越界：整条 run 拒绝，不让指标对着错的地图算")
    void outOfRangeGoldChunkRejectsWholeRun() {
        Harness harness = new Harness();
        // 文档重切过：只剩 1 块，item-1 的金标（第 1 块）已经不存在
        harness.index.records.clear();
        harness.index.records.add(new ChunkRecord("doc-1", 0, TOFU, "营养指南.txt", 1));

        assertThatThrownBy(() -> harness.start("ts-1"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("超出文档")
                .hasMessageContaining("共 1 块");

        assertThat(harness.commits()).isZero();
        assertThat(harness.runTasks.added).isEmpty();
    }

    @Test
    @DisplayName("金标都在范围内：起跑照常 fan-out，不写任何证据行")
    void inRangeGoldChunksStartTheRun() {
        Harness harness = new Harness();

        harness.start("ts-1");

        assertThat(harness.runTasks.added).hasSize(2);
        assertThat(harness.commits()).isEqualTo(1);
    }

    @Test
    @DisplayName("并行跑两个 run 会把排队时间算进 avg_latency_ms：第二个挡在提交之前")
    void runInProgressBlocksSecondOne() {
        Harness harness = new Harness();
        harness.start("ts-1");

        assertThatThrownBy(() -> harness.start("ts-1"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("已经有一次运行在跑");

        assertThat(harness.commits()).isEqualTo(1);
        assertThat(harness.runTasks.added).hasSize(2);
    }

    @Test
    @DisplayName("撞提交竞赛：检查与提交之间有并发窗口，部分唯一索引兜底时翻译成 400")
    void losingTheCommitRaceReportsConflict() {
        Harness harness = new Harness();
        harness.txManager.failOnCommit =
                new DuplicateKeyException("uq_eval_runs_running_per_testset");

        assertThatThrownBy(() -> harness.start("ts-1"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("已经有一次运行在跑");

        assertThat(harness.commits()).isZero(); // fan-out 的任务随事务回滚
    }

    @Test
    @DisplayName("跑完的 run 不挡下一次：两次 run 各自 fan-out 一整套任务，互不串")
    void finishedRunDoesNotBlockNextOne() {
        Harness harness = new Harness();
        String first = harness.start("ts-1").run().id();
        harness.evals.replaceRun(first, EvalRunStatus.DONE);

        String second = harness.start("ts-1").run().id();

        assertThat(harness.runTasks.added).hasSize(4);
        assertThat(harness.runTasks.added).extracting(entry -> entry.substring(0, entry.indexOf(':')))
                .containsExactlyInAnyOrderElementsOf(List.of(first, first, second, second));
    }

    @Test
    @DisplayName("测试集不存在：404 语义，一行都不写")
    void unknownTestsetRaisesWithoutStarting() {
        Harness harness = new Harness();

        assertThatThrownBy(() -> harness.start("ghost"))
                .isInstanceOf(TestSetNotFoundException.class);

        assertThat(harness.commits()).isZero();
        assertThat(harness.runTasks.added).isEmpty();
    }

    @Test
    @DisplayName("越权跑别人的评测集：与不存在同一个答案")
    void anotherUsersTestsetIsNotFound() {
        Harness harness = new Harness();

        assertThatThrownBy(() -> harness.service.startRun(BOB, "ts-1", null, true, true, null))
                .isInstanceOf(TestSetNotFoundException.class);

        assertThat(harness.commits()).isZero();
    }

    @Test
    @DisplayName("详情：逐题结果的派生口径（引文全在 / map / coverage）一并给出")
    void getRunReturnsDetailWithResults() {
        Harness harness = new Harness();
        String runId = harness.start("ts-1").run().id();
        harness.evals.results.put(runId, new ArrayList<>(List.of(result(0), result(1))));
        harness.evals.runs.put(runId, new EvalRun(runId, ALICE, "ts-1", EvalRunStatus.DONE,
                harness.evals.runs.get(runId).config(), Map.of("recall@5", 1.0, "queries", 2),
                null, CREATED_AT, null, 0, 2));

        EvalRunDetail detail = harness.service.getRun(ALICE, runId);

        assertThat(detail.run().progressDone()).isEqualTo(2);
        assertThat(detail.run().metrics()).containsEntry("recall@5", 1.0);
        assertThat(detail.items()).hasSize(2);
        var first = detail.items().getFirst();
        assertThat(first.testsetItemId()).isEqualTo("item-0");
        assertThat(first.hitRank()).isEqualTo(1);
        assertThat(first.evidenceRanks()).containsExactly(1);
        assertThat(first.recall()).isZero(); // 引文全在：2 段该回 1 段，不给过
        assertThat(first.map()).isEqualTo(0.5);
        assertThat(first.latencyMs()).isEqualTo(10.0);
        assertThat(first.evidenceTotal()).isEqualTo(2);
        assertThat(first.evidenceMatched()).isEqualTo(1);
        assertThat(first.channels()).isEmpty();
        assertThat(detail.items().get(1).map()).isEqualTo(0.25);
    }

    @Test
    @DisplayName("通道明细跟着出：每路一套同名同义的派生口径")
    void getRunExposesPerChannelDerivations() {
        Harness harness = new Harness();
        String runId = harness.start("ts-1").run().id();
        harness.evals.results.put(runId, new ArrayList<>(List.of(new EvalRunItem(
                "item-0", "豆腐有多少蛋白质？", 2, 10.0, 2, 1, List.of(2),
                List.of(new ChannelScore("dense", "豆腐有多少蛋白质？", List.of(1), 12L))))));

        var channels = harness.service.getRun(ALICE, runId).items().getFirst().channels();

        assertThat(channels).hasSize(1);
        assertThat(channels.getFirst().kind()).isEqualTo("dense");
        assertThat(channels.getFirst().ranks()).containsExactly(1);
        assertThat(channels.getFirst().recall()).isEqualTo(0); // 2 段只回 1 段
        assertThat(channels.getFirst().map()).isEqualTo(0.5);
    }

    @Test
    @DisplayName("看不存在的 run：404")
    void unknownRunRaises() {
        Harness harness = new Harness();

        assertThatThrownBy(() -> harness.service.getRun(ALICE, "ghost"))
                .isInstanceOf(RunNotFoundException.class);
    }

    @Test
    @DisplayName("看别人的 run：404，不是 403")
    void anotherUsersRunIsNotFound() {
        Harness harness = new Harness();
        String runId = harness.start("ts-1").run().id();

        assertThatThrownBy(() -> harness.service.getRun(BOB, runId))
                .isInstanceOf(RunNotFoundException.class);
    }

    @Test
    @DisplayName("历史列表只有摘要（不含逐题结果），且只有自己那次的")
    void listRunsReturnsSummaries() {
        Harness harness = new Harness();
        String runId = harness.start("ts-1").run().id();

        List<EvalRun> runs = harness.service.listRuns(ALICE, "ts-1");

        assertThat(runs).extracting(EvalRun::id).containsExactly(runId);
        // 别人的评测集与不存在的评测集同一个答案：连「有几条历史」都不泄漏
        assertThatThrownBy(() -> harness.service.listRuns(BOB, "ts-1"))
                .isInstanceOf(TestSetNotFoundException.class);
        assertThatThrownBy(() -> harness.service.listRuns(ALICE, "ghost"))
                .isInstanceOf(TestSetNotFoundException.class);
    }

    @Test
    @DisplayName("重跑失败题：任务复位 + run 翻回 running，再走既有消费链路")
    void rerunResetsTasksReopensRunAndCommits() {
        Harness harness = new Harness();
        String runId = harness.start("ts-1").run().id();
        harness.evals.replaceRun(runId, EvalRunStatus.FAILED);
        harness.runTasks.failed.put(runId, List.of("task-1"));
        int commitsBefore = harness.commits();

        EvalRunDetail detail = harness.service.rerunFailed(ALICE, runId);

        assertThat(detail.run().status()).isEqualTo(EvalRunStatus.RUNNING);
        assertThat(harness.runTasks.reset).containsExactly(runId);
        assertThat(harness.commits() - commitsBefore).isEqualTo(1);
    }

    @Test
    @DisplayName("重跑不重解析证据：复现的是这次 run 当年的行为，坐标半路被改掉就不是它了")
    void rerunDoesNotReresolveEvidence() {
        Harness harness = new Harness();
        String runId = harness.start("ts-1").run().id();
        harness.evals.replaceRun(runId, EvalRunStatus.FAILED);
        harness.runTasks.failed.put(runId, List.of("task-1"));
        // 索引已经变了：若重解析，起跑会拒绝而不是复位
        harness.index.records.set(0, new ChunkRecord("doc-1", 0, "整篇文档已被改写", "营养指南.txt", 2));

        harness.service.rerunFailed(ALICE, runId);

        assertThat(harness.evals.evidenceUpdates).isEmpty();
    }

    @Test
    @DisplayName("只有失败的 run 可以重跑")
    void onlyFailedRunsCanBeRerun() {
        Harness harness = new Harness();
        String runId = harness.start("ts-1").run().id();

        assertThatThrownBy(() -> harness.service.rerunFailed(ALICE, runId))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    @DisplayName("没有可重跑的失败任务：连空事务都不提交")
    void rerunWithoutFailedTasksIsRejected() {
        Harness harness = new Harness();
        String runId = harness.start("ts-1").run().id();
        harness.evals.replaceRun(runId, EvalRunStatus.FAILED);
        int commitsBefore = harness.commits();

        assertThatThrownBy(() -> harness.service.rerunFailed(ALICE, runId))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("没有可重跑");

        assertThat(harness.commits()).isEqualTo(commitsBefore);
    }

    @Test
    @DisplayName("重跑不存在的 run：404")
    void rerunUnknownRunRaises() {
        Harness harness = new Harness();

        assertThatThrownBy(() -> harness.service.rerunFailed(ALICE, "nope"))
                .isInstanceOf(RunNotFoundException.class);
    }
}
