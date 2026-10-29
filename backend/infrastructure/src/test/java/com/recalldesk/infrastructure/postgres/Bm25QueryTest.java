package com.recalldesk.infrastructure.postgres;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Stream;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;
import org.junit.jupiter.params.provider.ValueSource;

/**
 * 锁的是注入安全属性：Tantivy 的语法字符（: ( ) { } ! + 引号 反斜杠 | & ^ ~ * '）绝不能漏进查询串，
 * 否则未闭合引号或裸算子会让 @@@ 解析器直接抛错。输出恒为「若干对双引号包住、词内仅 \w 的词，
 * 空格相连」——用一个形状断言把"没有元字符能漏进词"和"没有多余引号"一并钉死。
 */
class Bm25QueryTest {

    private static final Pattern SAFE_SHAPE =
            Pattern.compile("\"\\w+\"( \"\\w+\")*", Pattern.UNICODE_CHARACTER_CLASS);

    private static final String[] METACHARACTERS = {
        ":", "(", ")", "{", "}", "!", "+", "\"", "\\", "|", "&", "^", "~", "*", "'"
    };

    @Test
    @DisplayName("单个中文词加引号")
    void singleChineseTermIsQuoted() {
        assertThat(Bm25Query.build("苹果")).isEqualTo("\"苹果\"");
    }

    @Test
    @DisplayName("多词空格相连（空格在 pg_search 里就是 OR）")
    void multipleTermsJoinWithSpace() {
        assertThat(Bm25Query.build("苹果 维C")).isEqualTo("\"苹果\" \"维C\"");
    }

    @ParameterizedTest
    @ValueSource(strings = {"。，、！？：；（）《》", "!@#$%^&*()", "", "   \t\n  "})
    @DisplayName("没词可查就交空串，让调用方短路")
    void nothingToSearchYieldsEmpty(String input) {
        assertThat(Bm25Query.build(input)).isEmpty();
    }

    @Test
    @DisplayName("裸算子被剥掉，剩下的按普通词查")
    void syntaxCharactersStripped() {
        assertThat(Bm25Query.build("a \"b\" && c++ ||")).isEqualTo("\"a\" \"b\" \"c\"");
    }

    @Test
    @DisplayName("塞一条裸查询进来也只会被切成普通词；(a:b) 收成单个词 ab")
    void injectionAttemptCollapsesToPlainTerms() {
        assertThat(Bm25Query.build("缺铁 吃什么 AND (a:b)")).isEqualTo("\"缺铁\" \"吃什么\" \"AND\" \"ab\"");
    }

    static Stream<String> metacharacters() {
        return Stream.of(METACHARACTERS);
    }

    @ParameterizedTest
    @MethodSource("metacharacters")
    @DisplayName("元字符混进词里也留不下")
    void metacharactersNeverSurvive(String meta) {
        String out = Bm25Query.build("缺" + meta + "铁吃什么");
        Matcher matcher = SAFE_SHAPE.matcher(out);
        assertThat(matcher.matches()).as("形状不合法：%s", out).isTrue();
        if (!meta.equals("\"")) {
            assertThat(out).doesNotContain(meta);
        }
    }

    @Test
    @DisplayName("null 输入不炸，交空串")
    void nullIsSafe() {
        assertThat(Bm25Query.build(null)).isEmpty();
    }
}
