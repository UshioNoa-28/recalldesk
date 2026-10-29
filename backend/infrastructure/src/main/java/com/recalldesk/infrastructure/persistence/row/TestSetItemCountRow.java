package com.recalldesk.infrastructure.persistence.row;

import lombok.Data;

/** 一个测试集的题目数（列表页的 itemCount，一次 GROUP BY 拿全）。 */
@Data
public class TestSetItemCountRow {

    private String testsetId;
    private Integer total;
}
