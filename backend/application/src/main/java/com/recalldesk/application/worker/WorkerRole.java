package com.recalldesk.application.worker;

import java.util.concurrent.CountDownLatch;

/**
 * 后台常驻角色的统一契约。
 *
 * 每个 worker（document 与 eval_run 两条链 × publisher/consumer）的进程样板完全一样，
 * 只差「跑哪个角色、根 logger 叫什么」：循环本体在 {@link BasePublisher} /
 * {@link BaseConsumer}，进程装配在 interfaces。
 *
 * @param stopSignal 归零即停。用 latch 而不是布尔标志，
 *     是为了让等待间隔也能立刻被退出信号打断，而不是睡满一个轮询周期才看得到。
 */
public interface WorkerRole {

    void run(CountDownLatch stopSignal);
}
