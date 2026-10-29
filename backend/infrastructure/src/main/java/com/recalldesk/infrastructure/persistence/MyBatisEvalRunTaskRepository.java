package com.recalldesk.infrastructure.persistence;

import com.recalldesk.domain.eval.EvalTaskStatus;
import com.recalldesk.domain.eval.EvalRunTask;
import com.recalldesk.domain.port.persistence.EvalRunTaskRepository;
import com.recalldesk.infrastructure.persistence.mapper.EvalRunTaskMapper;
import com.recalldesk.infrastructure.persistence.row.EvalRunTaskRow;
import com.recalldesk.infrastructure.persistence.row.StatusCountRow;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.Optional;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Repository;

/** 逐题评测任务发件箱（eval_run_tasks）的 MyBatis-Plus 实现：只挂调用方的事务，自己不提交。 */
@Repository
public class MyBatisEvalRunTaskRepository implements EvalRunTaskRepository {

    private static final int MAX_ERROR_LENGTH = 2000;

    private final EvalRunTaskMapper mapper;
    private final double retryBackoffBaseSeconds;

    public MyBatisEvalRunTaskRepository(
            EvalRunTaskMapper mapper,
            @Value("${recalldesk.eval-run-task.retry-backoff-base-seconds}") double retryBackoffBaseSeconds) {
        this.mapper = mapper;
        this.retryBackoffBaseSeconds = retryBackoffBaseSeconds;
    }

    @Override
    public void add(String runId, String itemId) {
        EvalRunTaskRow row = new EvalRunTaskRow();
        row.setId(UUID.randomUUID().toString());
        row.setRunId(runId);
        row.setItemId(itemId);
        row.setStatus(EvalTaskStatus.PENDING.wire());
        row.setAttempts(0);
        mapper.insert(row);
    }

    @Override
    public Optional<EvalRunTask> get(String taskId) {
        return Optional.ofNullable(mapper.selectById(taskId)).map(EvalRunTaskRow::toDomain);
    }

    @Override
    public List<EvalRunTask> listPending(int limit) {
        return mapper.listPendingForUpdate(limit).stream().map(EvalRunTaskRow::toDomain).toList();
    }

    @Override
    public void markQueued(String taskId) {
        requireHit(mapper.markQueued(taskId), taskId);
    }

    @Override
    public void markSuccess(String taskId) {
        requireHit(mapper.markSuccess(taskId), taskId);
    }

    @Override
    public void recordFailure(String taskId, String error) {
        requireHit(mapper.recordFailure(taskId, truncate(error), retryBackoffBaseSeconds), taskId);
    }

    @Override
    public void markFailed(String taskId) {
        requireHit(mapper.markFailed(taskId), taskId);
    }

    @Override
    public int resetFailedForRun(String runId) {
        return mapper.resetFailedForRun(runId);
    }

    @Override
    public Map<String, Integer> countByStatus(String runId) {
        Map<String, Integer> counts = new LinkedHashMap<>();
        for (StatusCountRow row : mapper.countByStatus(runId)) {
            counts.put(row.getStatus(), row.getTotal());
        }
        return counts;
    }

    private static String truncate(String error) {
        return error == null || error.length() <= MAX_ERROR_LENGTH ? error : error.substring(0, MAX_ERROR_LENGTH);
    }

    /** UPDATE 影响 0 行即任务不存在：worker 手上的 id 对不上，说明消息重复消费或行被级联删了。 */
    private static void requireHit(int updated, String taskId) {
        if (updated == 0) {
            throw new NoSuchElementException(taskId);
        }
    }

}
