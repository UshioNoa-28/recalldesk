package com.recalldesk.application.worker;

import com.recalldesk.domain.port.queue.StreamQueue;
import com.recalldesk.domain.port.ops.UnitOfWork;
import com.recalldesk.domain.task.TaskPolicy;
import java.util.Locale;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * 发布者基类：轮询 PENDING 任务并投递到队列的通用后台循环。
 *
 * 两条链路的 publisher（文档索引 / 逐题评测）只差三处：节奏参数来自各自的
 * {@link TaskPolicy}、领哪张表、投失败后怎么收尾。「轮询 + 异常兜底 + 可中断等待 +
 * 积压播报」这套循环是同一份，放在这里；领与投留给子类实现。
 *
 * 先投递后标 QUEUE：若两步之间崩溃，任务保持 PENDING，下一轮重复投递，
 * 消费者幂等消费，因此至少一次投递是安全的。这两步必须在同一事务里（发件箱的语义），
 * 所以子类的 publishPendingOnce 整体包在一个工作单元里。
 */
public abstract class BasePublisher implements WorkerRole {

    private static final Logger log = LoggerFactory.getLogger(BasePublisher.class);

    /** 积压播报的最小间隔：一轮 0.5s，每条都播会把有用行淹掉。 */
    private static final long BACKLOG_REPORT_NANOS = 30L * 1_000_000_000L;

    private final UnitOfWork unitOfWork;
    private final TaskPolicy policy;
    private final StreamQueue queue;
    private long lastBacklogReport = System.nanoTime();

    protected BasePublisher(UnitOfWork unitOfWork, TaskPolicy policy, StreamQueue queue) {
        this.unitOfWork = unitOfWork;
        this.policy = policy;
        this.queue = queue;
    }

    /**
     * 不停读 PENDING → 投递队列 → 标 QUEUE，直到收到退出信号。
     *
     * 单轮异常只记日志，下一轮重试：一条投不出去的任务由 recordFailure 退避，
     * 不该让整个投递循环死掉。
     */
    @Override
    public void run(CountDownLatch stopSignal) {
        String name = getClass().getSimpleName();
        log.info(
                "启动 {}: interval={}s batch={} max_attempts={}",
                name,
                String.format(Locale.ROOT, "%.2f", policy.publishIntervalSeconds()),
                policy.publishBatchSize(),
                policy.maxAttempts());
        while (stopSignal.getCount() > 0) {
            try {
                reportBacklog(publishPendingOnce());
            } catch (RuntimeException exc) {
                log.error("{} 轮询异常，下一轮重试", name, exc);
            }
            try {
                // 用 latch 的限时等待代替 sleep：退出信号一到就醒，不必睡满一个间隔
                stopSignal.await(Math.round(policy.publishIntervalSeconds() * 1000), TimeUnit.MILLISECONDS);
            } catch (InterruptedException exc) {
                Thread.currentThread().interrupt();
                return;
            }
        }
    }

    /** 读取一批 PENDING 并投递，返回成功数量（整批一个事务，提交由模板负责）。 */
    public abstract int publishPendingOnce();

    /**
     * 投递进展 + 组内未确认数，两种情形值得分开说：
     *
     * - 领满一整批：发件箱里还有货，下一轮还会领满，这就是「积压」的定义；
     * - 每 30 秒一条常态心跳：投完了但 worker 迟迟不 ACK，只有这个数看得出消费端卡住。
     *
     * 心跳没到点且本轮无事可做时什么都不说：空闲系统不该自己刷日志。
     */
    void reportBacklog(int published) {
        boolean fullBatch = published >= policy.publishBatchSize();
        long now = System.nanoTime();
        if (!fullBatch && now - lastBacklogReport < BACKLOG_REPORT_NANOS) {
            return;
        }
        lastBacklogReport = now;
        long unacked = queue.pendingCount();
        if (fullBatch) {
            log.warn("{} 积压: 本轮投满 {} 条（发件箱里还有），组内未确认 {} 条", name(), published, unacked);
        } else {
            log.info("{} 队列状态: 本轮投递 {} 条，组内未确认 {} 条", name(), published, unacked);
        }
    }

    /** 事务边界只在这里：仓储方法只登记，提交归工作单元。 */
    protected UnitOfWork unitOfWork() {
        return unitOfWork;
    }

    protected TaskPolicy policy() {
        return policy;
    }

    /** 日志里的身份名：子类叫 DocumentTaskPublisher，播报要说清是哪条链路。 */
    private String name() {
        return getClass().getSimpleName();
    }
}
