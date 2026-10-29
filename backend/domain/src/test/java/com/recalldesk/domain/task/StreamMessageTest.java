package com.recalldesk.domain.task;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.util.LinkedHashMap;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 队列侧值对象的口径测试：消息字段保序/只读，以及"假值"判定的边界（null/空串/纯空白）
 * （{@code not value} 与 {@code value or fallback}）。
 */
class StreamMessageTest {

    @Test
    @DisplayName("字段按投递顺序保序，且不可回写")
    void keepsFieldOrderAndIsImmutable() {
        Map<String, String> fields = new LinkedHashMap<>();
        fields.put("task_id", "task-1");
        fields.put("document_id", "doc-1");

        StreamMessage message = new StreamMessage("1-0", fields);
        fields.put("document_id", "doc-2"); // 构造后改原 map 不该影响消息

        assertThat(message.fields().keySet()).containsExactly("task_id", "document_id");
        assertThat(message.field("document_id")).isEqualTo("doc-1");
        assertThatThrownBy(() -> message.fields().put("x", "y"))
                .isInstanceOf(UnsupportedOperationException.class);
    }

    @Test
    @DisplayName("缺字段：null 与空串算缺，纯空白不算")
    void missingTreatsNullAndEmptyAsMissing() {
        assertThat(TaskFields.missing(null)).isTrue();
        assertThat(TaskFields.missing("")).isTrue();
        assertThat(TaskFields.missing(" ")).isFalse();
    }
}
