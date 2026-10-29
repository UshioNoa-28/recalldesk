package com.recalldesk.infrastructure.persistence.row;

import com.recalldesk.domain.eval.EvalRunItem;
import com.recalldesk.infrastructure.persistence.Jsonb;
import lombok.Data;

/** eval_run_items 表的一行（逐题结果），外加联查带出的题面。 */
@Data
public class EvalRunItemRow {

    private String id;
    private String runId;
    private String testsetItemId;
    private Integer hitRank;
    private Double latencyMs;
    private Integer evidenceTotal;
    private Integer evidenceMatched;
    private String evidenceRanksJson;
    private String channelsJson;

    /** 不属于 eval_run_items：listByRun 的 join 从 eval_testset_items 带出来，只读不写。 */
    private String query;

    /** 行 → 领域对象：名次与通道明细从两个 jsonb 列解码。 */
    public EvalRunItem toDomain() {
        return new EvalRunItem(
                testsetItemId,
                query,
                hitRank,
                latencyMs == null ? 0.0 : latencyMs,
                evidenceTotal == null ? 0 : evidenceTotal,
                evidenceMatched == null ? 0 : evidenceMatched,
                Jsonb.readRanks(evidenceRanksJson),
                Jsonb.readChannels(channelsJson));
    }
}
