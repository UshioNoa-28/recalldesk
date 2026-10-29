package com.recalldesk.interfaces.web;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * FastAPI/pydantic 形状的 422 明细，以及查询参数的"原始字符串"解析。
 *
 * 422 的 body 是 {@code {"detail":[{"type","loc","msg","input"[, "ctx"]}]}}，
 * 这里的工厂方法逐字段对齐 pydantic v2 的文案与键序（期望正文抓自真实服务，
 * 存在 {@code src/test/resources/contract/*.json}）。所以 web 层不用 Spring Validation：
 * 它的默认信封是 400 + 另一套 message，反推不回来。
 *
 * 查询参数一律以字符串进来的原因也在 {@code input}：pydantic 对 query 参数报告的是
 * 原始字符串（{@code "51"}），对 JSON body 报告的是解析后的值（{@code -1}）。
 */
public final class FastApiValidation {

    private FastApiValidation() {}

    /** 收集一批明细；有错就抛 422（FastAPI 一次请求报全部错误，不是撞一条报一条）。 */
    public static final class Errors {

        private final List<Map<String, Object>> details = new ArrayList<>();

        public boolean any() {
            return !details.isEmpty();
        }

        public void add(Map<String, Object> detail) {
            details.add(detail);
        }

        public List<Map<String, Object>> details() {
            return details;
        }

        /** 有错就抛；没错什么都不做。 */
        public void throwIfAny() {
            if (any()) {
                throw new ApiError(422, List.copyOf(details));
            }
        }
    }

    // ---- 明细构造：键序 type / loc / msg / input / ctx ----

    public static Map<String, Object> missing(List<Object> loc) {
        return detail("missing", loc, "Field required", null, null);
    }

    public static Map<String, Object> intParsing(List<Object> loc, Object input) {
        return detail("int_parsing", loc,
                "Input should be a valid integer, unable to parse string as an integer", input, null);
    }

    public static Map<String, Object> floatParsing(List<Object> loc, Object input) {
        return detail("float_parsing", loc,
                "Input should be a valid number, unable to parse string as a number", input, null);
    }

    public static Map<String, Object> boolParsing(List<Object> loc, Object input) {
        return detail("bool_parsing", loc,
                "Input should be a valid boolean, unable to interpret input", input, null);
    }

    public static Map<String, Object> greaterThanEqual(List<Object> loc, Object input, int ge) {
        return detail("greater_than_equal", loc,
                "Input should be greater than or equal to " + ge, input, ctx("ge", ge));
    }

    public static Map<String, Object> lessThanEqual(List<Object> loc, Object input, int le) {
        return detail("less_than_equal", loc,
                "Input should be less than or equal to " + le, input, ctx("le", le));
    }

    public static Map<String, Object> stringTooShort(List<Object> loc, Object input, int minLength) {
        return detail("string_too_short", loc,
                "String should have at least " + minLength + " " + plural(minLength, "character", "characters"),
                input, ctx("min_length", minLength));
    }

    public static Map<String, Object> stringTooLong(List<Object> loc, Object input, int maxLength) {
        return detail("string_too_long", loc,
                "String should have at most " + maxLength + " " + plural(maxLength, "character", "characters"),
                input, ctx("max_length", maxLength));
    }

    public static Map<String, Object> tooShort(List<Object> loc, Object input, int minLength, int actualLength) {
        return detail("too_short", loc,
                "List should have at least " + minLength + " " + plural(minLength, "item", "items")
                        + " after validation, not " + actualLength,
                input, listCtx("min_length", minLength, actualLength));
    }

    public static Map<String, Object> tooLong(List<Object> loc, Object input, int maxLength, int actualLength) {
        return detail("too_long", loc,
                "List should have at most " + maxLength + " " + plural(maxLength, "item", "items")
                        + " after validation, not " + actualLength,
                input, listCtx("max_length", maxLength, actualLength));
    }

    public static Map<String, Object> literalError(List<Object> loc, Object input, String expected) {
        return detail("literal_error", loc, "Input should be " + expected, input, ctx("expected", expected));
    }

    /** model_validator 抛的 ValueError：loc 停在 [body]，input 是整个 body，ctx.error 是空对象。 */
    public static Map<String, Object> valueError(List<Object> loc, Object input, String message) {
        Map<String, Object> ctx = new LinkedHashMap<>();
        ctx.put("error", new LinkedHashMap<>());
        return detail("value_error", loc, "Value error, " + message, input, ctx);
    }

    public static Map<String, Object> jsonInvalid(Object errorMessage) {
        Map<String, Object> ctx = new LinkedHashMap<>();
        ctx.put("error", errorMessage);
        return detail("json_invalid", List.of("body"), "JSON decode error", new LinkedHashMap<>(), ctx);
    }

    // ---- 查询参数解析：原样保留字符串，好让 input 与 pydantic 一致 ----

    /** {@code Query(1, ge=1)} 这种整数参数：缺省、类型错、越界各归各的明细。 */
    public static Integer intQuery(String name, String raw, Integer fallback, Integer ge, Integer le, Errors errors) {
        if (raw == null) {
            return fallback;
        }
        int parsed;
        try {
            parsed = Integer.parseInt(raw.strip());
        } catch (NumberFormatException exc) {
            errors.add(intParsing(List.of("query", name), raw));
            return null;
        }
        List<Object> loc = List.of("query", name);
        if (ge != null && parsed < ge) {
            errors.add(greaterThanEqual(loc, raw, ge));
        }
        if (le != null && parsed > le) {
            errors.add(lessThanEqual(loc, raw, le));
        }
        return parsed;
    }

    /** {@code Query(True)} 这种布尔参数。 */
    public static Boolean boolQuery(String name, String raw, boolean fallback, Errors errors) {
        if (raw == null) {
            return fallback;
        }
        Boolean parsed = parseBool(raw);
        if (parsed == null) {
            errors.add(boolParsing(List.of("query", name), raw));
        }
        return parsed;
    }

    /** pydantic 认的那几个真值写法（大小写不敏感）。 */
    private static Boolean parseBool(String raw) {
        return switch (raw.strip().toLowerCase()) {
            case "1", "on", "t", "true", "y", "yes" -> Boolean.TRUE;
            case "0", "off", "f", "false", "n", "no" -> Boolean.FALSE;
            default -> null;
        };
    }

    private static Map<String, Object> detail(
            String type, List<Object> loc, String msg, Object input, Map<String, Object> ctx) {
        Map<String, Object> detail = new LinkedHashMap<>();
        detail.put("type", type);
        detail.put("loc", loc);
        detail.put("msg", msg);
        detail.put("input", input);
        if (ctx != null) {
            detail.put("ctx", ctx);
        }
        return detail;
    }

    private static Map<String, Object> ctx(String key, Object value) {
        Map<String, Object> ctx = new LinkedHashMap<>();
        ctx.put(key, value);
        return ctx;
    }

    /** 列表类错误多带一个 field_type 与实际长度。 */
    private static Map<String, Object> listCtx(String key, int limit, int actualLength) {
        Map<String, Object> ctx = new LinkedHashMap<>();
        ctx.put("field_type", "List");
        ctx.put(key, limit);
        ctx.put("actual_length", actualLength);
        return ctx;
    }

    private static String plural(int count, String single, String many) {
        return count == 1 ? single : many;
    }
}
