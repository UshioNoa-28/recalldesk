package com.recalldesk.application.eval.dto;

import com.recalldesk.domain.eval.EvalRun;
import java.util.List;

/**
 * 运行详情 = run 元信息 + 逐题结果。
 *
 * 列表接口只给 {@link EvalRun}（不含逐题结果），进度与指标都在那一行里。
 */
public record EvalRunDetail(EvalRun run, List<EvalRunItemDto> items) {

    public EvalRunDetail {
        items = List.copyOf(items);
    }
}
