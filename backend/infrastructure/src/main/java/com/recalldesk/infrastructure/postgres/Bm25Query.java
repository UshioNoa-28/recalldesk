package com.recalldesk.infrastructure.postgres;

import java.util.StringJoiner;
import java.util.regex.Pattern;

/**
 * pg_search（Tantivy BM25）查询串的输入消毒。
 *
 * {@code col @@@ '串'} 走 Tantivy 查询解析器，{@code :} {@code (} {@code )} {@code {}} 和裸
 * AND/OR 都是语法，未闭合引号直接抛解析错误。消毒形状：切词 → 剥非词字符 → 逐词包双引号，
 * 空格分隔。实测空格在 pg_search 里就是 OR，所以自由文本原样进来也不会把一个词组变成必命中条件。
 */
public final class Bm25Query {

    /** UNICODE_CHARACTER_CLASS 让 \w 与 \s 都按 Unicode 走（中文与空白才算词边界）。 */
    private static final Pattern NON_WORD = Pattern.compile("[^\\w]+", Pattern.UNICODE_CHARACTER_CLASS);

    private static final Pattern WHITESPACE = Pattern.compile("\\s+", Pattern.UNICODE_CHARACTER_CLASS);

    private Bm25Query() {}

    /** 把自由文本转成安全的 BM25 查询；没词可查就返回空串（调用方短路）。 */
    public static String build(String queryText) {
        if (queryText == null || queryText.isBlank()) {
            return "";
        }
        StringJoiner terms = new StringJoiner(" ");
        for (String token : WHITESPACE.split(queryText)) {
            String cleaned = NON_WORD.matcher(token).replaceAll("");
            if (!cleaned.isEmpty()) {
                terms.add("\"" + cleaned + "\"");
            }
        }
        return terms.toString();
    }
}
