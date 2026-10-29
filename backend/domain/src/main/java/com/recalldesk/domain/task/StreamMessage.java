package com.recalldesk.domain.task;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 一条 Stream 消息：消息 ID + 字段表。
 *
 * 字段一律是字符串（Redis Stream 的字段本来就是字节串，我们的投递端只写字符串），
 * 保持"原样搬运"是刻意的：谁定义字段谁解析，队列本身不认识负载。
 * 保序副本（不是 Map.copyOf）是因为日志里要按投递顺序打字段名：
 * {@code list(data.keys())} 对齐。
 */
public record StreamMessage(String id, Map<String, String> fields) {

    public StreamMessage {
        fields = Collections.unmodifiableMap(new LinkedHashMap<>(fields));
    }

    /** 取一个字段；缺字段返回 null。 */
    public String field(String name) {
        return fields.get(name);
    }
}
