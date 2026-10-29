package com.recalldesk.infrastructure.persistence.row;

import lombok.Data;

/** 按题目状态分组的计数投影（finalize 的完成条件读它）。 */
@Data
public class StatusCountRow {

    private String status;
    private Integer total;
}
