package com.recalldesk.application.search;

import com.recalldesk.domain.retrieval.FusionConfig;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;

/** 多路结果怎么合。 */
public record FusionSpec(
        /** rrf（只看名次）或 weighted（路内归一化后按组加权求和）。 */
        String method,
        /** RRF 的分母常数；越大越不看头部名次差。weighted 档不用它。 */
        int rrfK,
        /** weighted 档的路内归一化方式：minmax 或 zscore。 */
        String norm,
        /** 按组给权重（dense / sparse），组内多条改写变体平摊。 */
        Map<String, Double> weights) {

    public static final List<String> METHODS = List.of("rrf", "weighted");
    public static final List<String> NORMS = List.of("minmax", "zscore");
    public static final List<String> CHANNEL_GROUPS = List.of("dense", "sparse");
    private static final int DEFAULT_RRF_K = 60;

    public FusionSpec {
        requireMember(method, METHODS, "融合方法");
        requireMember(norm, NORMS, "归一化方式");
        if (rrfK < 1) {
            throw new IllegalArgumentException("rrf_k 必须 >= 1");
        }
        for (Map.Entry<String, Double> entry : weights.entrySet()) {
            // 先判 null：不可变 map 的 containsKey(null) 自己就 NPE，而且 TreeSet 也收不下 null 键
            if (entry.getKey() == null) {
                throw new IllegalArgumentException("权重分组名不能为 null");
            }
            if (entry.getValue() == null) {
                throw new IllegalArgumentException("融合权重不能为 null");
            }
            if (entry.getValue() < 0) {
                throw new IllegalArgumentException("融合权重不能为负");
            }
        }
        Set<String> unknown = new TreeSet<>(weights.keySet());
        unknown.removeAll(CHANNEL_GROUPS);
        if (!unknown.isEmpty()) {
            throw new IllegalArgumentException("权重只能按组给（" + CHANNEL_GROUPS + "），多出 " + unknown);
        }
        // 不可变副本，且保住键序：出参里 weights 的键序与请求里的键序一致
        weights = Collections.unmodifiableMap(new LinkedHashMap<>(weights));
    }

    /** 默认档：RRF、k=60、两组权重各 1.0。 */
    public static FusionSpec defaults() {
        Map<String, Double> equal = new LinkedHashMap<>();
        equal.put("dense", 1.0);
        equal.put("sparse", 1.0);
        return new FusionSpec("rrf", DEFAULT_RRF_K, "minmax", equal);
    }

    /** 落库的完整配方 → 档位；给了什么就用什么，不并默认。null/全空 = 默认档。 */
    public static FusionSpec fromConfig(FusionConfig config) {
        if (config == null || isAllAbsent(config)) {
            return defaults();
        }
        return defaults().resolve(config, false);
    }

    /**
     * 在默认档之上覆盖请求里显式给出的那几项（逐项覆盖，weights 按键合并，
     * 所以 {sparse: 2} 是"sparse 加倍"而不是"只要 sparse"）。
     */
    public FusionSpec overlay(FusionConfig partial) {
        if (partial == null || isAllAbsent(partial)) {
            return this;
        }
        return resolve(partial, true);
    }

    /** 完整配方，落库与出参用。 */
    public FusionConfig toConfig() {
        return new FusionConfig(method, rrfK, norm, new LinkedHashMap<>(weights));
    }

    /** 通道名 → 权重组：dense_original 与 dense_variant 都归 dense。 */
    public static String channelGroup(String kind) {
        if (kind.startsWith("dense")) {
            return "dense";
        }
        if (CHANNEL_GROUPS.contains(kind)) {
            return kind;
        }
        throw new IllegalArgumentException("未知通道 kind: " + kind);
    }

    private FusionSpec resolve(FusionConfig partial, boolean mergeWeights) {
        // "没给"的口径：空串 / 0 / 空 map 都算没给，所以不能只判 null
        Map<String, Double> given = partial.weights() == null ? Map.of() : partial.weights();
        Map<String, Double> parsed = new LinkedHashMap<>();
        if (given.isEmpty()) {
            parsed.putAll(weights);
        } else {
            if (mergeWeights) {
                parsed.putAll(weights);
            }
            parsed.putAll(given);
        }
        String mergedMethod = orText(partial.method(), method);
        int mergedRrfK = partial.rrfK() == null || partial.rrfK() == 0 ? rrfK : partial.rrfK();
        return new FusionSpec(mergedMethod, mergedRrfK, orText(partial.norm(), norm), parsed);
    }

    private static boolean isAllAbsent(FusionConfig config) {
        return config.method() == null && config.rrfK() == null && config.norm() == null && config.weights() == null;
    }

    private static String orText(String given, String fallback) {
        return given == null || given.isEmpty() ? fallback : given;
    }

    private static void requireMember(String value, List<String> allowed, String label) {
        if (!allowed.contains(value)) {
            throw new IllegalArgumentException(label + "只能是 " + allowed + "，收到 '" + value + "'");
        }
    }
}
