package com.recalldesk.infrastructure.persistence.row;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import java.time.Instant;
import lombok.Data;

/** eval_testset_items 表的一行（题面；引文与落点在 evidence 子表）。 */
@Data
@TableName("eval_testset_items")
public class EvalTestSetItemRow {

    @TableId(type = IdType.INPUT)
    private String id;

    private String testsetId;
    private String query;
    private Instant createdAt;
}
