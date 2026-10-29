package com.recalldesk.domain;

import java.util.List;

/** 分页查询的返回值：当前页实体 + 符合条件的总数。 */
public record Page<T>(List<T> items, long total) {

    public Page {
        items = List.copyOf(items);
    }
}
