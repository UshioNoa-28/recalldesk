package com.recalldesk.infrastructure.redis;

import com.recalldesk.domain.port.queue.StreamQueue;
import com.recalldesk.domain.task.RedisBackend;
import com.recalldesk.domain.task.StreamMessage;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.springframework.data.domain.Range;
import org.springframework.data.redis.connection.RedisStreamCommands.XAddOptions;
import org.springframework.data.redis.connection.stream.Consumer;
import org.springframework.data.redis.connection.stream.MapRecord;
import org.springframework.data.redis.connection.stream.PendingMessage;
import org.springframework.data.redis.connection.stream.PendingMessages;
import org.springframework.data.redis.connection.stream.PendingMessagesSummary;
import org.springframework.data.redis.connection.stream.ReadOffset;
import org.springframework.data.redis.connection.stream.RecordId;
import org.springframework.data.redis.connection.stream.StreamOffset;
import org.springframework.data.redis.connection.stream.StreamReadOptions;
import org.springframework.data.redis.core.StreamOperations;
import org.springframework.data.redis.core.StringRedisTemplate;

/**
 * Redis Stream 任务队列基类：一组 (stream, group) 上的消费能力与公共配置。
 *
 * XREADGROUP / XACK / 认领孤儿这些消费侧细节都关在这里；enqueue 由子类显式实现
 * （各自的字段与日志），基类只提供公共配置与 XADD 的动作。
 * {@code app/infrastructure/redis/base.py} 一一对应。
 */
public class RedisStreamQueue implements StreamQueue {

    private final StringRedisTemplate redis;
    private final String stream;
    private final String group;
    private final RedisBackend backend;

    protected RedisStreamQueue(StringRedisTemplate redis, String stream, String group, RedisBackend backend) {
        this.redis = redis;
        this.stream = stream;
        this.group = group;
        this.backend = backend;
    }

    /**
     * XGROUP CREATE … MKSTREAM。
     *
     * Spring Data 的 {@code createGroup(key, readOffset, group)} 内部就是带 mkStream=true 的
     * XGROUP CREATE（MKSTREAM）；
     * 组已存在（BUSYGROUP）是幂等启动的常态，吞掉。
     */
    @Override
    public void ensureConsumerGroup() {
        try {
            streamOps().createGroup(stream, ReadOffset.from("0"), group);
        } catch (RuntimeException exc) {
            if (!isBusyGroup(exc)) {
                throw exc;
            }
        }
    }

    @Override
    public List<StreamMessage> readNew(String consumerName, int count, int blockMs) {
        List<MapRecord<String, String, String>> records = streamOps()
                .read(
                        Consumer.from(group, consumerName),
                        StreamReadOptions.empty().count(count).block(Duration.ofMillis(blockMs)),
                        StreamOffset.create(stream, ReadOffset.lastConsumed()));
        return toMessages(records);
    }

    @Override
    public void ack(String messageId) {
        streamOps().acknowledge(stream, group, messageId);
    }

    /**
     * 认领空闲超时的未确认消息。
     *
     * 认领孤儿本来该用 XAUTOCLAIM（带 min-idle / count / 游标）。Spring Data Redis 3.5 的
     * {@code RedisStreamCommands} 只有 xClaim / xClaimJustId，没有 XAUTOCLAIM 的封装，
     * 所以这里用语义等价的两步：XPENDING 取组内 PEL 从头部开始的前 count 条，
     * 再 XCLAIM——XCLAIM 自带 min-idle 判定，不够老的消息原封不动返回空，结果与
     * "只认领空闲超时的未确认消息、单次最多 count 条"一致。差别只在没有游标：
     * 每轮都从 PEL 头扫，够老的消息一定会被再次看到，不会被跳过。
     */
    @Override
    public List<StreamMessage> claimOrphans(String consumerName, int count) {
        PendingMessages pending = streamOps().pending(stream, group, Range.<String>unbounded(), count);
        if (pending == null || pending.isEmpty()) {
            return List.of();
        }
        RecordId[] ids = new RecordId[pending.size()];
        int index = 0;
        for (PendingMessage message : pending) {
            ids[index++] = message.getId();
        }
        List<MapRecord<String, String, String>> claimed =
                streamOps().claim(stream, group, consumerName, Duration.ofMillis(backend.claimMinIdleMs()), ids);
        return toMessages(claimed);
    }

    /**
     * XPENDING &lt;key&gt; &lt;group&gt;：组内 PEL 的条数。
     *
     * 抛异常时返回 0 而不是往上丢：调用方是投递循环里的日志行，为它打死一轮投递
     * 不值得，何况「读不到积压」与「没有积压」在日志里的处置本来就该一样。
     */
    @Override
    public long pendingCount() {
        try {
            PendingMessagesSummary summary = streamOps().pending(stream, group);
            return summary == null ? 0 : summary.getTotalPendingMessages();
        } catch (RuntimeException exc) {
            return 0;
        }
    }

    /** 当前 stream 名（子类拼日志用）。 */
    protected String stream() {
        return stream;
    }

    /** XADD：字段原样写入，带 {@code MAXLEN ~ maxlen} 近似裁剪。 */
    protected String add(Map<String, String> fields) {
        // approximateTrimming(true) 就是 MAXLEN ~：~ 近似裁剪，
        // 快，允许长度略超 maxlen。
        RecordId id = streamOps()
                .add(stream, fields, XAddOptions.maxlen(backend.maxlen()).approximateTrimming(true));
        return id == null ? null : id.getValue();
    }

    private StreamOperations<String, String, String> streamOps() {
        return redis.opsForStream();
    }

    private static List<StreamMessage> toMessages(List<MapRecord<String, String, String>> records) {
        if (records == null || records.isEmpty()) {
            return List.of();
        }
        List<StreamMessage> messages = new ArrayList<>(records.size());
        for (MapRecord<String, String, String> record : records) {
            messages.add(new StreamMessage(record.getId().getValue(), record.getValue()));
        }
        return messages;
    }

    /** 错误链里带 BUSYGROUP 就是"组已存在"（驱动不保证错误类型，只能查文本）。 */
    private static boolean isBusyGroup(Throwable error) {
        for (Throwable current = error; current != null; current = current.getCause()) {
            String message = current.getMessage();
            if (message != null && message.contains("BUSYGROUP")) {
                return true;
            }
        }
        return false;
    }
}
