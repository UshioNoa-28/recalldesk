package com.recalldesk.application.eval.dto;

import com.recalldesk.domain.eval.EvalTestSet;
import com.recalldesk.domain.eval.EvalTestSetItem;
import java.util.List;

/** 评测集详情 = 元信息 + 它的全部题目（列表接口只有前者，进度不在这里重复统计）。 */
public record EvalTestSetDetail(EvalTestSet testSet, List<EvalTestSetItem> items) {

    public EvalTestSetDetail {
        items = List.copyOf(items);
    }
}
