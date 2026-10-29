package com.recalldesk.domain.retrieval;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class QueryRewriteTest {

    @Test
    @DisplayName("关键词拼成稀疏查询串；没关键词时退回第一条变体")
    void sparseTextUsesKeywordsOrFirstVariant() {
        assertThat(new QueryRewrite(List.of("q1"), List.of("apple", "vitamin")).sparseText())
                .isEqualTo("apple vitamin");
        assertThat(new QueryRewrite(List.of("q1", "q2"), List.of()).sparseText()).isEqualTo("q1");
    }

    @Test
    @DisplayName("空变体列表在构造期被拒：坏响应不该静默退化成不改写")
    void emptyVariantsRejected() {
        assertThatThrownBy(() -> new QueryRewrite(List.of(), List.of()))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("queries 至少要有 1 条");
        assertThatThrownBy(() -> new QueryRewrite(null, null)).isInstanceOf(IllegalArgumentException.class);
    }
}
