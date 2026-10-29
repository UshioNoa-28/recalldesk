package com.recalldesk.application.eval;

import com.recalldesk.application.eval.dto.EvalRunDetail;
import com.recalldesk.application.eval.dto.EvalRunItemDto;
import com.recalldesk.domain.eval.EvalRun;
import com.recalldesk.domain.eval.EvalRunConfig;
import com.recalldesk.domain.eval.EvalRunStatus;
import com.recalldesk.domain.eval.EvalTestSet;
import com.recalldesk.domain.eval.EvalTestSetItem;
import com.recalldesk.domain.eval.EvidenceQuote;
import com.recalldesk.domain.exception.eval.RunNotFoundException;
import com.recalldesk.domain.exception.eval.TestSetNotFoundException;
import com.recalldesk.domain.port.ops.UnitOfWork;
import com.recalldesk.domain.port.persistence.ChunkIndex;
import com.recalldesk.domain.port.persistence.EvalRepository;
import com.recalldesk.domain.port.persistence.EvalRunRepository;
import com.recalldesk.domain.port.persistence.EvalRunTaskRepository;
import com.recalldesk.domain.retrieval.FusionConfig;
import com.recalldesk.application.search.FusionSpec;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.dao.DuplicateKeyException;

/**
 * 评测运行的用例编排：起一个 run、看进度、看结果。
 *
 * 开跑 = 同一事务里写 running 行 + 按题目 fan-out 逐题任务（eval_run_tasks），
 * 投递与检索都由后台进程接手，这里只做起跑前的判断和读：POST 立刻返回 run_id，
 * 客户端轮询详情接口看 progress_done / status。
 *
 * 构造参数里有交互式检索的默认档（top-k + 融合档），这两个值归组合根读，
 * 所以本类不做 @Component 自动扫，bean 由 interfaces 的 ApplicationServiceConfiguration 提供。
 */
public class EvalRunService {

    private static final String BUSY_MESSAGE = "这个评测集已经有一次运行在跑，等它结束再开新的";
    /** 起跑报错最多列几条，其余只报数量（一整份文档被换过时问题会成串出现）。 */
    private static final int MAX_REPORTED_PROBLEMS = 10;

    private final EvalRepository evals;
    private final EvalRunRepository runs;
    private final EvalRunTaskRepository runTasks;
    private final ChunkIndex chunkIndex;
    private final UnitOfWork unitOfWork;
    private final int defaultTopK;
    private final FusionSpec defaultFusion;

    public EvalRunService(
            EvalRepository evals,
            EvalRunRepository runs,
            EvalRunTaskRepository runTasks,
            ChunkIndex chunkIndex,
            UnitOfWork unitOfWork,
            int defaultTopK,
            FusionSpec defaultFusion) {
        this.evals = evals;
        this.runs = runs;
        this.runTasks = runTasks;
        this.chunkIndex = chunkIndex;
        this.unitOfWork = unitOfWork;
        this.defaultTopK = defaultTopK;
        this.defaultFusion = defaultFusion == null ? FusionSpec.defaults() : defaultFusion;
    }

    /**
     * 开一次评测：重解析 → 判断 → run 行 + 逐题任务行一起提交，交给队列。
     *
     * 重解析放在起跑是因为坐标是派生值：导入之后文档可能被重新索引（分块参数换了、块边界移动），
     * 拿旧坐标去数新块，指标会静默错位——高分照旧，只是数错了。这里每次 run 前按引文重算，
     * 漂移就当场改写落点，一句话真的找不到了就整条 run 拒绝并说是哪句。
     *
     * 一道题都没有就不让跑——空评测会给出 recall@k = 0，那是个假数字而不是「检索很差」。
     *
     * fan-out 和 run 行同事务是发件箱的定义：提交了 run 就必然有任务可投，崩在两不管的
     * 中间不存在——所以这里不需要任何启动扫。
     *
     * @param fusion partial 配方（只给想改的键），叠在装配默认档上解析成完整档位再落库；
     *     非法的 method/norm/权重在构造 FusionSpec 时就抛。
     */
    public EvalRunDetail startRun(
            String userId, String testSetId, Integer topK, boolean queryRewrite, boolean rerank,
            FusionConfig fusion) {
        requireTestSet(userId, testSetId);
        requireIdle(userId, testSetId);

        List<EvalTestSetItem> items = checkEvidenceInRange(testSetId);
        if (items.isEmpty()) {
            throw new IllegalArgumentException("评测集里还没有题目，先上传题目再跑");
        }

        int k = topK == null || topK == 0 ? defaultTopK : topK;
        String runId = UUID.randomUUID().toString();
        // 落的是解析后的完整档位（不是请求原样）：半个 config 描述不了实验，
        // 事后看这份 run 要能一字不差说出它用了哪种融合
        EvalRunConfig config = new EvalRunConfig(
                k, queryRewrite, rerank, defaultFusion.overlay(fusion).toConfig());
        try {
            unitOfWork.execute(() -> {
                runs.createRun(runId, userId, testSetId, config);
                for (EvalTestSetItem item : items) {
                    runTasks.add(runId, item.id());
                }
            });
        } catch (DuplicateKeyException exc) {
            // requireIdle 的「查 running 再插入」之间有并发窗口，DB 里的部分唯一索引
            // （一个测试集最多一个 running）是最终防线；这里把冲突翻译成 400 给前端。
            // run 行带任务行一起回滚，没有留下孤儿任务
            throw new IllegalArgumentException(BUSY_MESSAGE, exc);
        }
        return getRun(userId, runId);
    }

    /** 运行详情：状态 + 进度 + 聚合指标 + 逐题结果。 */
    public EvalRunDetail getRun(String userId, String runId) {
        EvalRun run = requireRun(userId, runId);
        return new EvalRunDetail(run, runs.listRunItems(runId).stream().map(EvalRunItemDto::of).toList());
    }

    /**
     * 重跑失败 run 里的失败题：任务复位 + run 翻回 running，再走既有消费链路。
     *
     * 不重解析证据：复跑要复现的是这次 run 当年的行为，坐标半路被改掉就不是它了。
     * 已有结果行的题由 hasRunResult 幂等跳过，不重复计；全部任务落定后 finalize
     * 基于全部结果行重算指标。同测试集有别的 running 时拒（startRun 同款规矩，
     * 部分唯一索引兜并发窗口）。
     */
    public EvalRunDetail rerunFailed(String userId, String runId) {
        EvalRun run = requireRun(userId, runId);
        if (run.status() != EvalRunStatus.FAILED) {
            throw new IllegalArgumentException("只有失败的运行可以重跑失败题");
        }
        requireIdle(userId, run.testsetId());
        try {
            // 复位与重开同一事务：没有可重做的任务就在事务内炸掉，回滚掉那次空写
            unitOfWork.execute(() -> {
                if (runTasks.resetFailedForRun(runId) == 0) {
                    throw new IllegalArgumentException("这次运行没有可重跑的失败任务");
                }
                runs.reopenRun(runId);
            });
        } catch (DuplicateKeyException exc) {
            throw new IllegalArgumentException("这个评测集已经有其它运行在跑", exc);
        }
        return getRun(userId, runId);
    }

    /** 某测试集的历史运行（不含逐题结果），按创建时间降序。 */
    public List<EvalRun> listRuns(String userId, String testSetId) {
        requireTestSet(userId, testSetId);
        return runs.listRuns(userId, testSetId);
    }

    /**
     * 校验每题的金标仍然落在文档范围内；有一处对不上就整条 run 拒绝。
     *
     * 金标是用户指定的 (document_id, chunk_index)，系统不做任何文本匹配——但分块参数变过
     * 之后，同一个块号指向的可能是另一段话。所以这里只做范围校验（块号仍在 0..块数-1）：
     * 越界说明文档被重切过，宁可拒绝也不要让指标对着错的地图算出一个假分数。
     *
     * 块数没变、内容却换了的极端情况（同长度编辑）这里发现不了，那是分块参数不可回退的
     * 已知代价，靠「改分块参数要重建测试集」这条使用约束兜。
     */
    private List<EvalTestSetItem> checkEvidenceInRange(String testSetId) {
        List<EvalTestSetItem> items = evals.listTestSetItems(testSetId);
        Map<String, Integer> chunkCounts = new LinkedHashMap<>();
        List<String> problems = new ArrayList<>();

        for (int number = 1; number <= items.size(); number++) {
            EvalTestSetItem item = items.get(number - 1);
            String label = "第 " + number + " 题";
            for (EvidenceQuote evidence : item.evidence()) {
                int chunkCount = chunkCounts.computeIfAbsent(
                        evidence.documentId(), id -> chunkIndex.getDocumentChunks(id).size());
                if (evidence.chunkIndex() >= chunkCount) {
                    problems.add(label + " 的金标块 " + evidence.chunkIndex()
                            + " 超出文档 " + evidence.documentId() + " 的当前范围（共 " + chunkCount + " 块）");
                }
            }
        }
        if (!problems.isEmpty()) {
            throw new IllegalArgumentException(describe(problems));
        }
        return items;
    }

    /**
     * 同一个测试集同时只让跑一个 run。
     *
     * 不是为了数据（各 run 的结果行互不干扰），是为了量出来的延迟准：两个 run 并行
     * 就是把 embedding 服务的排队时间算进 avg_latency_ms。这里的检查只是给用户友好的
     * 报错和进度，真正的原子性由 eval_runs 上的部分唯一索引兜底。
     */
    private void requireIdle(String userId, String testSetId) {
        runs.listRuns(userId, testSetId).stream()
                .filter(run -> run.status() == EvalRunStatus.RUNNING)
                .findFirst()
                .ifPresent(running -> {
                    throw new IllegalArgumentException("这个评测集已经有一次运行在跑（"
                            + running.progressDone() + "/" + running.progressTotal() + "），等它结束再开新的");
                });
    }

    private EvalTestSet requireTestSet(String userId, String testSetId) {
        return evals.getTestSet(userId, testSetId).orElseThrow(() -> new TestSetNotFoundException(testSetId));
    }

    private EvalRun requireRun(String userId, String runId) {
        return runs.getRunOwned(userId, runId).orElseThrow(() -> new RunNotFoundException(runId));
    }

    private static String describe(List<String> problems) {
        StringBuilder text = new StringBuilder("评测集的证据坐标已失效，先修正再跑：\n");
        int shown = Math.min(problems.size(), MAX_REPORTED_PROBLEMS);
        for (int i = 0; i < shown; i++) {
            text.append(i + 1).append(". ").append(problems.get(i)).append('\n');
        }
        if (problems.size() > shown) {
            text.append("……还有 ").append(problems.size() - shown).append(" 条同类问题");
        }
        return text.toString().strip();
    }

    private static String shorten(String text) {
        String single = text == null ? "" : text.replaceAll("\\s+", " ").strip();
        return single.length() <= 40 ? single : single.substring(0, 40) + "…";
    }
}
