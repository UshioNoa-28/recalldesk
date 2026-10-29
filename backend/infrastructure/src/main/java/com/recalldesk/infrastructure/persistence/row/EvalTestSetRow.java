package com.recalldesk.infrastructure.persistence.row;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.recalldesk.domain.eval.EvalTestSet;
import java.time.Instant;
import lombok.Data;

/** eval_testsets 表的一行。 */
@Data
@TableName("eval_testsets")
public class EvalTestSetRow {

    @TableId(type = IdType.INPUT)
    private String id;

    private String userId;
    private String name;
    private Instant createdAt;

    /**
     * 行 → 领域对象。itemCount 不是本表的列：它由 items 表按集聚合出来（进度是数出来的），
     * 所以由调用方带进来。
     */
    public EvalTestSet toDomain(int itemCount) {
        return new EvalTestSet(id, userId, name, itemCount, createdAt);
    }
}
