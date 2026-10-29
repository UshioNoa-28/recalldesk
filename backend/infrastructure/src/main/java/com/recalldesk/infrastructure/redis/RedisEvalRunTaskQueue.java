package com.recalldesk.infrastructure.redis;

import com.recalldesk.domain.port.queue.EvalRunTaskQueue;
import com.recalldesk.domain.task.RedisBackend;
import com.recalldesk.domain.task.TaskPolicy;
import java.util.LinkedHashMap;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;

/** Eval 逐题评测任务的 Redis Stream 队列：独立 stream/group，与出题/文档队列互不干扰。 */
public class RedisEvalRunTaskQueue extends RedisStreamQueue implements EvalRunTaskQueue {

    private static final Logger log = LoggerFactory.getLogger(RedisEvalRunTaskQueue.class);

    public RedisEvalRunTaskQueue(StringRedisTemplate redis, TaskPolicy policy, RedisBackend backend) {
        super(redis, policy.stream(), policy.consumerGroup(), backend);
    }

    @Override
    public String enqueue(String taskId, String runId, String itemId) {
        Map<String, String> fields = new LinkedHashMap<>();
        fields.put("task_id", taskId);
        fields.put("run_id", runId);
        fields.put("item_id", itemId);
        String messageId = add(fields);
        log.info(
                "任务已投递: stream={} msg_id={} task={} run={} item={}",
                stream(),
                messageId,
                taskId,
                runId,
                itemId);
        return messageId;
    }
}
