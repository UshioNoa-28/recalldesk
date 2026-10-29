package com.recalldesk.domain.task;

/**
 * 一条异步任务链路的完整策略：队列寻址 + 投递节奏 + 重试预算。
 *
 * 一份对象同时喂给该链路的 queue / publisher / consumer，省得三处各自读配置的同名旋钮、
 * 彼此漂移——一份不可变值对象，
 * 字段名与默认值逐条对齐（文档 0.5s/50/10 次/30s、出题 2s/20/5 次/30s、
 * 逐题评测 1s/50/3 次/10s）。
 *
 * 只装"一整条链路"的旋钮；Redis 侧的公共参数在 {@link RedisBackend}。
 */
public record TaskPolicy(
        String stream,
        String consumerGroup,
        double publishIntervalSeconds,
        int publishBatchSize,
        int maxAttempts,
        double retryBackoffSeconds) {
}
