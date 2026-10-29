package com.recalldesk.infrastructure.persistence.row;

import lombok.Data;

/** eval_run_items 按 run 分组的计数行：run 的 done 进度（结果行有几行 = 跑完几题）。 */
@Data
public class RunCountRow {

    private String runId;
    private Integer total;
}
