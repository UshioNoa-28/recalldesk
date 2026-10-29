package com.recalldesk.infrastructure.redis;

import com.recalldesk.domain.port.queue.DocumentTaskQueue;
import com.recalldesk.domain.task.RedisBackend;
import com.recalldesk.domain.task.TaskPolicy;
import java.util.LinkedHashMap;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;

/** 文档索引任务的 Redis Stream 队列：独立 stream/group，与 eval 队列互不干扰。 */
public class RedisDocumentTaskQueue extends RedisStreamQueue implements DocumentTaskQueue {

    private static final Logger log = LoggerFactory.getLogger(RedisDocumentTaskQueue.class);

    public RedisDocumentTaskQueue(StringRedisTemplate redis, TaskPolicy policy, RedisBackend backend) {
        super(redis, policy.stream(), policy.consumerGroup(), backend);
    }

    @Override
    public String enqueue(String taskId, String documentId) {
        Map<String, String> fields = new LinkedHashMap<>();
        fields.put("task_id", taskId);
        fields.put("document_id", documentId);
        String messageId = add(fields);
        log.info(
                "任务已投递: stream={} msg_id={} task={} doc={}",
                stream(),
                messageId,
                taskId,
                documentId);
        return messageId;
    }
}
