package com.recalldesk.domain.task;

/**
 * 所有 Stream 队列共享的底层参数（与具体任务类型无关）。
 *
 * maxlen 是 XADD 时的近似裁剪上限：队列表是"在途消息的搬运带"，不是档案，堆到百万级
 * 只会让 XPENDING / XCLAIM 变慢；claimMinIdleMs 决定"多老算孤儿"——
 * 空闲超过它的未确认消息可以被别的消费者认领。
 *
 * 没有游标起点：认领走
 * XPENDING（取 PEL 头部前 count 条）+ XCLAIM 的等价两步路径，按构造就没有游标。
 */
public record RedisBackend(int maxlen, int claimMinIdleMs) {
}
