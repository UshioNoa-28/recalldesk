package com.recalldesk.infrastructure.persistence;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.recalldesk.domain.eval.ChannelScore;
import com.recalldesk.domain.eval.EvalRunConfig;
import java.util.List;
import java.util.Map;

/**
 * jsonb 列的读写编解码：库里的 JSON 与领域形状之间的唯一一道门。
 *
 * 命名策略跟 web 层一样是 SNAKE_CASE——config/结果落库的键名就是 API 契约的键名，
 * 两边各配一套迟早分叉。反序列化刻意不认未知键：读 config_json 时遇到未知键
 * `cast(EvalRunConfig, row.config_json)`，根本不校验，历史行里多出来的键不该让新代码炸。
 *
 * 读回来的类型靠调用方点名（List<ChannelScore> 这种嵌套泛型 Jackson 猜不出来）。
 */
public final class Jsonb {

    private static final ObjectMapper MAPPER = new ObjectMapper()
            .setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE)
            .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);

    private Jsonb() {}

    /** 写成 jsonb 能收的文本；null 原样传下去（列可空时就是 NULL）。 */
    public static String write(Object value) {
        if (value == null) {
            return null;
        }
        try {
            return MAPPER.writeValueAsString(value);
        } catch (Exception e) {
            throw new IllegalStateException("jsonb 序列化失败: " + value.getClass(), e);
        }
    }

    public static EvalRunConfig readRunConfig(String json) {
        if (json == null || json.isEmpty()) {
            return null;
        }
        try {
            return MAPPER.readValue(json, EvalRunConfig.class);
        } catch (Exception e) {
            throw new IllegalStateException("eval run config 解析失败: " + json, e);
        }
    }

    /** 聚合指标：原样读出交给出参，不在这里重新定义口径。 */
    public static Map<String, Object> readMetrics(String json) {
        if (json == null || json.isEmpty()) {
            return null;
        }
        try {
            return MAPPER.readValue(json, Map.class);
        } catch (Exception e) {
            throw new IllegalStateException("metrics_json 解析失败: " + json, e);
        }
    }

    public static List<Integer> readRanks(String json) {
        if (json == null || json.isEmpty()) {
            return List.of();
        }
        try {
            return MAPPER.readValue(json, List.class);
        } catch (Exception e) {
            throw new IllegalStateException("evidence_ranks_json 解析失败: " + json, e);
        }
    }

    public static List<ChannelScore> readChannels(String json) {
        if (json == null || json.isEmpty()) {
            return List.of();
        }
        try {
            return MAPPER.readValue(json, MAPPER.getTypeFactory()
                    .constructCollectionType(List.class, ChannelScore.class));
        } catch (Exception e) {
            throw new IllegalStateException("channels_json 解析失败: " + json, e);
        }
    }
}
