package com.recalldesk.infrastructure.redis;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.doReturn;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

import com.recalldesk.domain.task.RedisBackend;
import com.recalldesk.domain.task.StreamMessage;
import com.recalldesk.domain.task.TaskPolicy;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.ArgumentMatchers;
import org.springframework.data.domain.Range;
import org.springframework.data.redis.RedisSystemException;
import org.springframework.data.redis.connection.RedisStreamCommands.XAddOptions;
import org.springframework.data.redis.connection.stream.Consumer;
import org.springframework.data.redis.connection.stream.MapRecord;
import org.springframework.data.redis.connection.stream.PendingMessage;
import org.springframework.data.redis.connection.stream.PendingMessages;
import org.springframework.data.redis.connection.stream.ReadOffset;
import org.springframework.data.redis.connection.stream.RecordId;
import org.springframework.data.redis.connection.stream.StreamOffset;
import org.springframework.data.redis.connection.stream.StreamReadOptions;
import org.springframework.data.redis.core.StreamOperations;
import org.springframework.data.redis.core.StringRedisTemplate;

/**
 * Redis Stream 队列适配器的命令级测试：验证基类把端口方法翻译成正确的 Redis 命令，
 * 以及两条链（文档 / 逐题评测）各自投递到独立的 stream / group（对应
 * {@code tests/test_redis_stream_queues.py} 逐条对应，出题那条链已删）。
 *
 * 断言直接对着 {@code StreamOperations} 的调用参数，不连真 Redis：这里要钉的是
 * "哪个 stream、哪个 group、哪些字段、什么 MAXLEN"，不是 Redis 自己的行为。
 */
class RedisStreamQueueTest {

    private static final TaskPolicy DOCUMENT_POLICY =
            new TaskPolicy("anna_rag_document_tasks", "anna_rag_document_workers", 0.5, 50, 10, 30.0);
    private static final TaskPolicy EVAL_RUN_POLICY =
            new TaskPolicy("anna_rag_eval_run_tasks", "anna_rag_eval_run_workers", 1.0, 50, 3, 10.0);
    private static final RedisBackend BACKEND = new RedisBackend(10_000, 60_000);

    private StringRedisTemplate redis;
    private StreamOperations<String, String, String> ops;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        redis = mock(StringRedisTemplate.class);
        ops = mock(StreamOperations.class);
        doReturn(ops).when(redis).opsForStream();
    }

    // ---- 基类：组管理 / 读取 / ACK / 认领孤儿 ----

    @Test
    @DisplayName("ensureConsumerGroup 建组：XGROUP CREATE 从 0 开始（Spring 自带 MKSTREAM）")
    void createsConsumerGroup() {
        new RedisDocumentTaskQueue(redis, DOCUMENT_POLICY, BACKEND).ensureConsumerGroup();

        verify(ops).createGroup("anna_rag_document_tasks", ReadOffset.from("0"), "anna_rag_document_workers");
    }

    @Test
    @DisplayName("组已存在（BUSYGROUP）不抛：幂等启动的常态")
    void ignoresBusyGroup() {
        given(ops.createGroup(any(), any(), any()))
                .willThrow(new RedisSystemException(
                        "XGROUP CREATE failed", new RuntimeException("BUSYGROUP Consumer Group name already exists")));

        new RedisDocumentTaskQueue(redis, DOCUMENT_POLICY, BACKEND).ensureConsumerGroup(); // 不应抛异常
    }

    @Test
    @DisplayName("其它 Redis 错误照抛，不当成幂等")
    void rethrowsOtherErrors() {
        RedisDocumentTaskQueue queue = new RedisDocumentTaskQueue(redis, DOCUMENT_POLICY, BACKEND);
        given(ops.createGroup(any(), any(), any())).willThrow(new RedisSystemException("boom", new RuntimeException("NOGROUP something wrong")));

        assertThatThrownBy(queue::ensureConsumerGroup).isInstanceOf(RedisSystemException.class);
    }

    @Test
    @DisplayName("readNew：XREADGROUP 的结果摊平成 (id, fields)")
    void flattensReadGroupResult() {
        given(ops.read(any(Consumer.class), any(StreamReadOptions.class), any(StreamOffset.class)))
                .willReturn(List.of(MapRecord.create("anna_rag_document_tasks", fields("task_id", "task-1", "document_id", "doc-1"))
                        .withId(RecordId.of("1-0"))));

        List<StreamMessage> messages = new RedisDocumentTaskQueue(redis, DOCUMENT_POLICY, BACKEND)
                .readNew("consumer-1", 1, 2000);

        assertThat(messages).containsExactly(new StreamMessage("1-0", fields("task_id", "task-1", "document_id", "doc-1")));
    }

    @Test
    @DisplayName("readNew：没有新消息时给空列表，不返回 null")
    void readNewReturnsEmptyListWhenNothingArrived() {
        given(ops.read(any(Consumer.class), any(StreamReadOptions.class), any(StreamOffset.class))).willReturn(List.of());

        assertThat(new RedisDocumentTaskQueue(redis, DOCUMENT_POLICY, BACKEND).readNew("consumer-1", 1, 2000))
                .isEmpty();
    }

    @Test
    @DisplayName("ack 发 XACK 到本队列的 stream + group")
    void acksOnOwnStreamAndGroup() {
        new RedisDocumentTaskQueue(redis, DOCUMENT_POLICY, BACKEND).ack("1-0");

        verify(ops).acknowledge("anna_rag_document_tasks", "anna_rag_document_workers", "1-0");
    }

    @Test
    @DisplayName("claimOrphans：XPENDING + XCLAIM（min-idle 不够的消息由 XCLAIM 自己挡掉）")
    void claimsOrphansThroughPendingPlusClaim() {
        RecordId orphan = RecordId.of("9-9");
        given(ops.pending("anna_rag_document_tasks", "anna_rag_document_workers", Range.<String>unbounded(), 2))
                .willReturn(new PendingMessages(
                        "anna_rag_document_workers",
                        List.of(new PendingMessage(
                                orphan, Consumer.from("anna_rag_document_workers", "consumer-0"), Duration.ofSeconds(90), 1))));
        given(ops.claim(eq("anna_rag_document_tasks"), eq("anna_rag_document_workers"), eq("consumer-2"), any(Duration.class), any(RecordId.class)))
                .willReturn(List.of(MapRecord.create("anna_rag_document_tasks", fields("task_id", "task-9", "document_id", "doc-9"))
                        .withId(orphan)));

        List<StreamMessage> claimed = new RedisDocumentTaskQueue(redis, DOCUMENT_POLICY, BACKEND)
                .claimOrphans("consumer-2", 2);

        assertThat(claimed).containsExactly(new StreamMessage("9-9", fields("task_id", "task-9", "document_id", "doc-9")));
        verify(ops).claim(
                "anna_rag_document_tasks",
                "anna_rag_document_workers",
                "consumer-2",
                Duration.ofMillis(60_000),
                RecordId.of("9-9"));
    }

    @Test
    @DisplayName("claimOrphans：PEL 空时不发 XCLAIM")
    void skipsClaimWhenPendingIsEmpty() {
        given(ops.pending(any(), ArgumentMatchers.<String>any(), any(), eq(2L)))
                .willReturn(new PendingMessages("anna_rag_document_workers", List.of()));

        assertThat(new RedisDocumentTaskQueue(redis, DOCUMENT_POLICY, BACKEND).claimOrphans("consumer-2", 2))
                .isEmpty();
        verify(ops, never()).claim(any(), any(), any(), any(Duration.class), any(RecordId.class));
    }

    // ---- 两条链的队列：字段与目标 stream / group ----

    @Test
    @DisplayName("文档队列：两个字段保序，MAXLEN ~ 近似裁剪")
    void documentQueueEnqueuesDocumentFields() {
        given(ops.add(eq("anna_rag_document_tasks"), anyMap(), any(XAddOptions.class)))
                .willReturn(RecordId.of("1-0"));

        String messageId = new RedisDocumentTaskQueue(redis, DOCUMENT_POLICY, BACKEND)
                .enqueue("task-1", "doc-1");

        assertThat(messageId).isEqualTo("1-0");
        ArgumentCaptor<Map<String, String>> fields = mapCaptor();
        ArgumentCaptor<XAddOptions> options = optionsCaptor();
        verify(ops).add(eq("anna_rag_document_tasks"), fields.capture(), options.capture());
        assertThat(fields.getValue().keySet()).containsExactly("task_id", "document_id");
        assertThat(fields.getValue()).containsExactlyEntriesOf(fields(
                "task_id", "task-1", "document_id", "doc-1"));
        assertThat(options.getValue().getMaxlen()).isEqualTo(10_000);
        assertThat(options.getValue().isApproximateTrimming()).isTrue(); // ~ 必须保留
    }

    @Test
    @DisplayName("逐题评测队列：投到 run stream，三个字段（task/run/item）")
    void evalRunQueueEnqueuesRunFields() {
        given(ops.add(eq("anna_rag_eval_run_tasks"), anyMap(), any(XAddOptions.class)))
                .willReturn(RecordId.of("3-0"));

        String messageId = new RedisEvalRunTaskQueue(redis, EVAL_RUN_POLICY, BACKEND)
                .enqueue("task-3", "run-1", "item-1");

        assertThat(messageId).isEqualTo("3-0");
        ArgumentCaptor<Map<String, String>> fields = mapCaptor();
        verify(ops).add(eq("anna_rag_eval_run_tasks"), fields.capture(), any(XAddOptions.class));
        assertThat(fields.getValue().keySet()).containsExactly("task_id", "run_id", "item_id");
    }

    /** 交替的 key/value 参数拼成保序 map（断言字段顺序用）。 */
    private static Map<String, String> fields(String... keyValues) {
        Map<String, String> fields = new LinkedHashMap<>();
        for (int index = 0; index < keyValues.length; index += 2) {
            fields.put(keyValues[index], keyValues[index + 1]);
        }
        return fields;
    }

    @SuppressWarnings({"unchecked", "rawtypes"})
    private static ArgumentCaptor<Map<String, String>> mapCaptor() {
        return (ArgumentCaptor) ArgumentCaptor.forClass(Map.class);
    }

    private static ArgumentCaptor<XAddOptions> optionsCaptor() {
        return ArgumentCaptor.forClass(XAddOptions.class);
    }
}
