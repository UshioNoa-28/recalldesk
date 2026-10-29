package com.recalldesk.application.auth;

import com.recalldesk.domain.exception.users.EmailCodeInvalidException;
import com.recalldesk.domain.exception.users.EmailCodeTooFrequentException;
import com.recalldesk.domain.port.auth.EmailCodeStore;
import com.recalldesk.domain.port.auth.EmailSender;
import com.recalldesk.domain.users.UserIdentity;
import java.security.SecureRandom;
import java.time.Duration;

/**
 * 邮箱验证码：发码与校验。
 *
 * 两件事刻意分开：{@link #sendCode} 只写信，{@link #requireValidCode} 只验码。
 * 注册用例在查完全部前置条件（用户名/邮箱是否被占）之后才验码，这样「名字被占了」
 * 不会先烧掉一次验证码；而发码本身不查账号是否已存在——「这个邮箱注册过没有」
 * 属于注册时的错误，不该在发码接口上被枚举出来。
 *
 * 码是六位十进制、{@link SecureRandom} 生成：它要扛的是「十分钟内猜 100 万分之一」，
 * 真正挡住爆破的是每个邮箱只有一份码 + 一次性消费 + 冷却期，不是码的长度。
 */
public class EmailCodeService {

    private static final int CODE_BOUND = 1_000_000;
    private static final SecureRandom RANDOM = new SecureRandom();

    private final EmailCodeStore store;
    private final EmailSender sender;
    private final Duration ttl;

    public EmailCodeService(EmailCodeStore store, EmailSender sender, Duration ttl) {
        this.store = store;
        this.sender = sender;
        this.ttl = ttl;
    }

    /**
     * 发一枚验证码到该邮箱。
     *
     * 冷却期用存储的 NX 占位实现：两次「先查再发」在并发下会双双通过，于是同一邮箱
     * 一分钟收两封、后一封把前一封顶掉——用户手上那封就成了废码。
     *
     * 发信失败要把冷却位还回去（release 就是让码过期），否则用户重试会撞上自己造成的冷却。
     */
    public void sendCode(String rawEmail) {
        String email = UserIdentity.of(rawEmail).value();
        String code = nextCode();
        if (!store.reserve(email, code, ttl)) {
            throw new EmailCodeTooFrequentException(Math.max(1, store.cooldownRemaining(email).toSeconds()));
        }
        try {
            sender.sendVerificationCode(email, code, Math.max(1, ttl.toMinutes()));
        } catch (RuntimeException exc) {
            store.compareAndRemove(email, code); // 没送出去就别占着冷却位
            throw exc;
        }
    }

    /** 校验并消费一枚码；不对/过期/已用过一律同一个异常（不给爆破的人分档信息）。 */
    public void requireValidCode(String rawEmail, String code) {
        String email = UserIdentity.of(rawEmail).value();
        if (code == null || !store.compareAndRemove(email, code.strip())) {
            throw new EmailCodeInvalidException();
        }
    }

    private static String nextCode() {
        return String.format("%06d", RANDOM.nextInt(CODE_BOUND));
    }
}
