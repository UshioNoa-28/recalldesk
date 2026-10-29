package com.recalldesk.application.worker;

import com.recalldesk.domain.port.queue.StreamQueue;
import com.recalldesk.domain.port.ops.UnitOfWork;
import com.recalldesk.domain.task.StreamMessage;
import com.recalldesk.domain.task.TaskPolicy;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * 消费者基类：领孤儿 → 读新消息 → 分发处理 → ACK 的通用后台循环。
 *
 * 两条链路的 consumer（索引 / 逐题评测）只差两处：消息负载里要校验哪些字段、
 * 任务本体怎么执行。「循环 + 孤儿认领 + ACK 规则 + 追踪 ID 恢复」这套语义是同一份，
 * 放在这里；字段提取与处理留给子类实现。
 *
 * ACK 规则：handleTask 正常返回（业务成功或失败都已落库）就 ACK；它抛异常
 * （典型是事务提交失败）则不 ACK，消息留在 PEL 等认领重投 —— DB 状态没变，
 * 重跑靠子类自己的幂等守卫，是安全的。
 */
public abstract class BaseConsumer implements WorkerRole {

    private static final Logger log = LoggerFactory.getLogger(BaseConsumer.class);

    /** 读新消息短阻塞（2s）：退出信号最多延迟这么久被看到。 */
    static final int READ_COUNT = 1;
    static final int READ_BLOCK_MS = 2000;
    /** 孤儿认领每轮最多 2 条，防止崩溃恢复期一条消息喂饱一轮。 */
    static final int ORPHAN_CLAIM_COUNT = 2;
    /** 消费循环撞上非致命异常后的退避：Redis/PG 抖一下不该空转打卡。 */
    private static final long LOOP_ERROR_SLEEP_MS = 1000;
    /** 慢任务播报线：一次索引要打 embedding，超过它就值得单独留一行（含追迹 ID）。 */
    private static final long SLOW_TASK_MS = 5000;

    private final StreamQueue queue;
    private final UnitOfWork unitOfWork;
    private final TaskPolicy policy;
    private final String consumerName;

    protected BaseConsumer(
            StreamQueue queue,
            UnitOfWork unitOfWork,
            TaskPolicy policy,
            String consumerNamePrefix,
            String consumerName) {
        this.queue = queue;
        this.unitOfWork = unitOfWork;
        this.policy = policy;
        // 消费者名的默认值带进程号：容器编排里要认出具体是哪个副本在消费
        this.consumerName = consumerName == null ? consumerNamePrefix + "-" + ProcessHandle.current().pid() : consumerName;
    }

    /**
     * 不停消费队列任务，直到收到退出信号。
     *
     * 本服务独占一个进程，业务调用直接阻塞当前线程即可，不需要线程池。
     */
    @Override
    public void run(CountDownLatch stopSignal) {
        String name = getClass().getSimpleName();
        log.info("启动 {}: consumer={}", name, consumerName);
        queue.ensureConsumerGroup();
        while (stopSignal.getCount() > 0) {
            try {
                claimAndProcessOrphans();
                for (StreamMessage message : queue.readNew(consumerName, READ_COUNT, READ_BLOCK_MS)) {
                    processSingleMessage(message);
                }
                if (Thread.currentThread().isInterrupted()) {
                    return;
                }
            } catch (RuntimeException exc) {
                if (stopSignal.getCount() == 0) {
                    // 退出信号之后连接被容器关掉，读消息会抛 "Connection closed"：
                    // 那是关机的收尾噪音，不是消费故障
                    return;
                }
                log.error("{} 消费循环异常", name, exc);
                if (sleep(LOOP_ERROR_SLEEP_MS)) {
                    return;
                }
            }
        }
    }

    /** 认领空闲超时的未确认消息（消费者崩溃遗留）：认领失败是非致命的。 */
    void claimAndProcessOrphans() {
        try {
            for (StreamMessage message : queue.claimOrphans(consumerName, ORPHAN_CLAIM_COUNT)) {
                log.warn("认领孤儿任务: id={} data={}", message.id(), message.fields());
                processSingleMessage(message);
            }
        } catch (RuntimeException exc) {
            log.warn("认领孤儿任务异常（非致命）", exc);
        }
    }

    /** 处理单条消息；事务提交成功才 ACK，失败留给认领重投。 */
    void processSingleMessage(StreamMessage message) {
        Map<String, String> ids = extractTaskIds(message.fields());
        if (ids == null) {
            // 毒消息：缺字段或取值非法，重投也不会变好，记错误日志后 ACK 掉
            log.error("消息字段缺失或非法，直接 ACK: msg_id={} fields={}", message.id(), message.fields());
            queue.ack(message.id());
            return;
        }

        log.info("{} 处理任务: msg_id={} {}", getClass().getSimpleName(), message.id(), ids);
        long started = System.nanoTime();
        try {
            handleTask(ids);
        } catch (RuntimeException exc) {
            // 事务提交失败等未预期异常：不 ACK，消息留在 PEL，
            // 由认领（XPENDING + XCLAIM）重试（DB 状态未变，幂等）。
            log.error("任务处理异常（不 ACK，等待认领）: {}", ids, exc);
            return;
        }
        long tookMs = (System.nanoTime() - started) / 1_000_000;
        if (tookMs >= SLOW_TASK_MS) {
            log.warn("慢任务: msg_id={} 耗时={}ms {}", message.id(), tookMs, ids);
        }
        queue.ack(message.id());
    }

    /**
     * 从消息负载提取 handleTask 需要的字段；缺字段或取值非法返回 null（基类记日志后直接 ACK 掉）。
     *
     * 返回的是保序 Map：日志按投递顺序打出来，读起来稳定。
     */
    protected abstract Map<String, String> extractTaskIds(Map<String, String> fields);

    /**
     * 执行任务本体。
     *
     * 业务失败须在方法内落库并正常返回（由基类 ACK）；只有事务提交失败才允许抛出
     * （基类不 ACK，留给重投）。
     */
    protected abstract void handleTask(Map<String, String> ids);

    /** 事务边界只在这里：仓储方法只登记，提交归工作单元。 */
    protected UnitOfWork unitOfWork() {
        return unitOfWork;
    }

    protected TaskPolicy policy() {
        return policy;
    }

    /** 按顺序拼一个字段表（三条链路的字段表都是"取出几个键"，保序便于日志与对拍）。 */
    protected static Map<String, String> fields(String... keyValues) {
        Map<String, String> fields = new LinkedHashMap<>();
        for (int index = 0; index < keyValues.length; index += 2) {
            fields.put(keyValues[index], keyValues[index + 1]);
        }
        return fields;
    }

    /** @return true 表示被中断（调用方该退出） */
    private static boolean sleep(long millis) {
        try {
            Thread.sleep(millis);
            return false;
        } catch (InterruptedException exc) {
            Thread.currentThread().interrupt();
            return true;
        }
    }
}
