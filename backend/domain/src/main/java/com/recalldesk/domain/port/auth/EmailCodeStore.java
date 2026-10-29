package com.recalldesk.domain.port.auth;

import java.time.Duration;

/**
 * 邮箱验证码的暂存：发一次、存一份、验一次就作废。
 *
 * 三件事的语义必须分开，别混成一个「查了再写」：
 * {@link #reserve} 是一次 NX 写入，用来做冷却期（两次「先查再写」会让并发请求双双通过）；
 * {@link #compareAndRemove} 必须是「读出来比对、一样就删」的原子动作，
 * 否则同一个码可以被重放两次注册两个账号。
 *
 * 键空间与 TTL 都由调用方给：存储不认识「邮箱」是什么，也不该认识——它只是一把 KV。
 */
public interface EmailCodeStore {

    /**
     * 占住这个邮箱的冷却位并写入验证码。
     *
     * @return 抢到冷却位返回 true；冷却期内已经有码（或刚发过）返回 false
     */
    boolean reserve(String email, String code, Duration cooldown);

    /** 校验并一次性消费：码对得上就删除并返回 true；否则 false（码本身不动，仍可再试）。 */
    boolean compareAndRemove(String email, String code);

    /** 距离这个邮箱下次可发还剩多久；没有冷却返回零。 */
    Duration cooldownRemaining(String email);
}
