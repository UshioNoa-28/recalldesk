package com.recalldesk.infrastructure.persistence.row;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.recalldesk.domain.eval.EvalRunTask;
import com.recalldesk.domain.eval.EvalTaskStatus;
import java.time.Instant;
import lombok.Data;

/** eval_run_tasks 表的一行（逐题评测任务发件箱）。 */
@Data
@TableName("eval_run_tasks")
public class EvalRunTaskRow {

    @TableId(type = IdType.INPUT)
    private String id;

    private String runId;
    private String itemId;
    private String status;
    private Integer attempts;
    private String lastError;
    private Instant nextRetryAt;
    private Instant createdAt;
    private Instant queuedAt;

    public EvalRunTask toDomain() {
        return new EvalRunTask(
                id, runId, itemId, EvalTaskStatus.from(status), attempts == null ? 0 : attempts,
                lastError, createdAt, queuedAt);
    }
}
