package com.recalldesk.domain.port.queue;

import com.recalldesk.domain.task.StreamMessage;
import java.util.List;

/**
 * Redis Stream 消费侧的共有能力，与具体任务类型无关（{@code BaseConsumer} 依赖它）。
 *
 * 两条任务链路（文档索引 / 逐题评测）共享这一套消费语义，
 * 只有 enqueue 的消息字段不同——所以 enqueue 留在各自的子接口，这里只放
 * 组管理 / 读取 / ACK / 认领孤儿。
 *
 * 方法是阻塞的：后台循环跑在自己的线程上。
 */
public interface StreamQueue {

    /** 确保消费者组存在（已存在则忽略）。 */
    void ensureConsumerGroup();

    /**
     * 读取组内未分配的新消息（XREADGROUP + {@code >}），阻塞至多 blockMs。
     *
     * @return 按投递顺序的消息；没有新消息时返回空列表（不返回 null）
     */
    List<StreamMessage> readNew(String consumerName, int count, int blockMs);

    /** 确认消息处理完成（XACK）。 */
    void ack(String messageId);

    /**
     * 组内「已投出但没 ACK」的消息数（PEL 深度）——积压的直接读数。
     *
     * 这是排障用的观测量，不是正确性依赖：读失败或组还没建时给 0 即可，别让一次
     * 日志把投递循环打死。PENDING 里还没投出的量不在这儿，那由发件箱表说话。
     */
    long pendingCount();

    /**
     * 认领空闲超时的未确认消息（消费者崩溃遗留）。
     *
     * 只认领空闲超过 claimMinIdleMs 的消息，
     * 单次最多 count 条。
     */
    List<StreamMessage> claimOrphans(String consumerName, int count);
}
