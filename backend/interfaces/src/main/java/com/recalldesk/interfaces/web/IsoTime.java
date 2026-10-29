package com.recalldesk.interfaces.web;

import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;

/**
 * 出参时间的统一形状：UTC、带 {@code +00:00}、微秒非零时给 6 位小数。
 *
 * 不直接用 Jackson 序列化 Instant，是因为 Java 会写成 {@code ...Z} 且精度不定；
 * 前端就按这个文本解析。仓里所有出参时间都是
 * {@code Instant.now()} 或库里的 timestamptz（微秒精度），所以这里只做这一种形状。
 */
public final class IsoTime {

    private static final DateTimeFormatter SECONDS = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss");

    private IsoTime() {}

    public static String format(Instant instant) {
        if (instant == null) {
            return null;
        }
        OffsetDateTime utc = instant.atOffset(ZoneOffset.UTC);
        String base = utc.format(SECONDS);
        int micros = utc.getNano() / 1000;
        // microsecond==0 时不写小数部分（保持形状稳定）
        return micros == 0 ? base + "+00:00" : base + "." + String.format("%06d", micros) + "+00:00";
    }
}
