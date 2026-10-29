package com.recalldesk.infrastructure.persistence;

import com.recalldesk.domain.eval.EvalRun;
import com.recalldesk.domain.eval.EvalRunConfig;
import com.recalldesk.domain.eval.EvalRunItem;
import com.recalldesk.domain.eval.EvalRunStatus;
import com.recalldesk.domain.port.persistence.EvalRunRepository;
import com.recalldesk.infrastructure.persistence.mapper.EvalRunItemMapper;
import com.recalldesk.infrastructure.persistence.mapper.EvalRunMapper;
import com.recalldesk.infrastructure.persistence.mapper.EvalTestSetItemMapper;
import com.recalldesk.infrastructure.persistence.row.EvalRunItemRow;
import com.recalldesk.infrastructure.persistence.row.EvalRunRow;
import com.recalldesk.infrastructure.persistence.row.RunCountRow;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.springframework.stereotype.Repository;

/** eval_runs + eval_run_items 两张表的读写；指标怎么算、run 什么时候收尾归应用层。 */
@Repository
public class MyBatisEvalRunRepository implements EvalRunRepository {

    private final EvalRunMapper runs;
    private final EvalRunItemMapper runItems;
    private final EvalTestSetItemMapper items;

    public MyBatisEvalRunRepository(
            EvalRunMapper runs, EvalRunItemMapper runItems, EvalTestSetItemMapper items) {
        this.runs = runs;
        this.runItems = runItems;
        this.items = items;
    }

    @Override
    public void createRun(String runId, String userId, String testsetId, EvalRunConfig config) {
        EvalRunRow row = new EvalRunRow();
        row.setId(runId);
        row.setUserId(userId);
        row.setTestsetId(testsetId);
        row.setStatus(EvalRunStatus.RUNNING.wire());
        row.setConfigJson(Jsonb.write(config));
        row.setMetricsJson(null);
        row.setErrorMessage(null);
        runs.insert(row);
    }

    @Override
    public void recordRunItem(String runId, EvalRunItem result) {
        EvalRunItemRow row = new EvalRunItemRow();
        row.setId(UUID.randomUUID().toString());
        row.setRunId(runId);
        row.setTestsetItemId(result.testsetItemId());
        row.setHitRank(result.hitRank());
        row.setLatencyMs(result.latencyMs());
        row.setEvidenceTotal(result.evidenceTotal());
        row.setEvidenceMatched(result.evidenceMatched());
        row.setEvidenceRanksJson(Jsonb.write(result.evidenceRanks()));
        row.setChannelsJson(Jsonb.write(result.channels()));
        runItems.insert(row);
    }

    @Override
    public void finishRun(String runId, EvalRunStatus status, Map<String, Object> metrics, String errorMessage) {
        runs.finishIfRunning(runId, status.wire(), Jsonb.write(metrics), errorMessage);
    }

    @Override
    public Optional<EvalRun> getRun(String runId) {
        EvalRunRow row = runs.selectById(runId);
        if (row == null) {
            return Optional.empty();
        }
        int done = scoredCounts(List.of(runId)).getOrDefault(runId, 0);
        return Optional.of(row.toDomain(done, items.countByTestSet(row.getTestsetId())));
    }

    @Override
    public Optional<EvalRun> getRunOwned(String userId, String runId) {
        // 别人的 run 与不存在的 run 同一个答案：详情接口不该用来探 id
        return getRun(runId).filter(run -> run.userId().equals(userId));
    }

    @Override
    public List<EvalRun> listRuns(String userId, String testsetId) {
        List<EvalRunRow> rows = runs.listByTestset(userId, testsetId);
        // 同一测试集的 run 共用一个 total（当前题数），done 各数各的
        Map<String, Integer> done = scoredCounts(rows.stream().map(EvalRunRow::getId).toList());
        int total = items.countByTestSet(testsetId);
        return rows.stream().map(row -> row.toDomain(done.getOrDefault(row.getId(), 0), total)).toList();
    }

    @Override
    public List<EvalRunItem> listRunItems(String runId) {
        return runItems.listByRun(runId).stream().map(EvalRunItemRow::toDomain).toList();
    }

    @Override
    public boolean hasRunResult(String runId, String testsetItemId) {
        return runItems.countResult(runId, testsetItemId) > 0;
    }

    @Override
    public int deleteRunsReferencingDocument(String documentId) {
        return runs.deleteReferencingDocument(documentId);
    }

    @Override
    public void reopenRun(String runId) {
        runs.reopen(runId);
    }

    private Map<String, Integer> scoredCounts(List<String> runIds) {
        if (runIds.isEmpty()) {
            return Map.of();
        }
        Map<String, Integer> counts = new HashMap<>();
        for (RunCountRow row : runItems.countByRun(runIds)) {
            counts.put(row.getRunId(), row.getTotal());
        }
        return counts;
    }

}
