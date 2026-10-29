package com.recalldesk.infrastructure.persistence.row;

import com.recalldesk.domain.eval.EvalRun;
import com.recalldesk.domain.eval.EvalRunStatus;
import com.recalldesk.infrastructure.persistence.Jsonb;
import java.time.Instant;
import lombok.Data;

/**
 * eval_runs 表的一行。
 *
 * 两个 jsonb 列在这里就是原始 JSON 文本：MP 会把 String 按 varchar 绑参，PG 直接拒收
 * （column is of type jsonb but expression is of type character varying），
 * 所以读写都不走 BaseMapper，SQL 里显式 CAST，编解码交给 Jsonb。
 */
@Data
public class EvalRunRow {

    private String id;
    private String userId;
    private String testsetId;
    private String status;
    private String configJson;
    private String metricsJson;
    private String errorMessage;
    private Instant createdAt;
    private Instant finishedAt;

    /**
     * 行 → 领域对象。两个 jsonb 列在这里解码；进度（done/total）不是本表的列，
     * 是 eval_run_items 数出来的，由调用方带进来。
     */
    public EvalRun toDomain(int progressDone, int progressTotal) {
        return new EvalRun(
                id,
                userId,
                testsetId,
                EvalRunStatus.from(status),
                Jsonb.readRunConfig(configJson),
                Jsonb.readMetrics(metricsJson),
                errorMessage,
                createdAt,
                finishedAt,
                progressDone,
                progressTotal);
    }
}
