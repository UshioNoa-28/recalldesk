package com.recalldesk.interfaces.worker;

import com.recalldesk.application.worker.WorkerRole;
import java.util.concurrent.CountDownLatch;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;

/**
 * worker 进程的统一入口：跑一个 {@link WorkerRole}，把 SIGINT/SIGTERM 变成退出信号。
 *
 * 每个 worker 进程的样板（建容器 → 取 service → 装信号 → run）
 * 在这里只有一份，差别只剩「跑哪个角色、根 logger 叫什么」——那两件事都在装配处点名，
 * 一个进程只装一个角色（见 WorkerConfiguration 的 @ConditionalOnProperty）。
 *
 * 退出信号用 JVM 的 shutdown hook：容器编排的 SIGTERM 一进来就归零，
 * 循环在下一个可中断点（等投递间隔 / 读消息的 block 超时）自行收尾退出。
 */
public class WorkerRunner implements ApplicationRunner {

    private final Logger log;
    private final String roleName;
    private final WorkerRole role;

    public WorkerRunner(String loggerName, WorkerRole role) {
        this.log = LoggerFactory.getLogger(loggerName);
        this.roleName = role.getClass().getSimpleName();
        this.role = role;
    }

    @Override
    public void run(ApplicationArguments args) {
        CountDownLatch stopSignal = new CountDownLatch(1);
        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            log.info("收到退出信号，通知 {} 停止", roleName);
            stopSignal.countDown();
        }, "recalldesk-worker-shutdown"));
        role.run(stopSignal);
    }
}
