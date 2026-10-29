package com.recalldesk.infrastructure.redis;

import com.recalldesk.domain.port.auth.EmailCodeStore;
import java.time.Duration;
import java.util.List;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;

/**
 * Redis 上的邮箱验证码：一个邮箱一个键，键里就是那六个数字。
 *
 * 为什么用 Redis 而不是表：验证码是十分钟就死的一次性凭证，不是资源。建表就要面对
 * 「谁清理过期行」，而 Redis 的 TTL 天生会自己收；而且「冷却期」本身就是一次 SET NX。
 *
 * 校验用 Lua 而不是 GET + DEL：两步之间有一次往返，同一个码连发两次就能各自通过、
 * 注册出两个账号。脚本里比对与删除是一段原子执行，重复的码一定在第二个人那里失败。
 */
public class RedisEmailCodeStore implements EmailCodeStore {

    private static final String PREFIX = "email-code:";

    /** 比对成功才删除：失败时把码留在原地，用户还有机会把最后一位改对。 */
    private static final DefaultRedisScript<Long> COMPARE_AND_REMOVE = new DefaultRedisScript<>(
            "if redis.call('GET', KEYS[1]) == ARGV[1] then "
                    + "return redis.call('DEL', KEYS[1]) else return 0 end",
            Long.class);

    private final StringRedisTemplate redis;

    public RedisEmailCodeStore(StringRedisTemplate redis) {
        this.redis = redis;
    }

    @Override
    public boolean reserve(String email, String code, Duration cooldown) {
        // 冷却期与有效期是同一个键：发码即占位，十分钟内同一邮箱只有最新那一枚码有效
        return Boolean.TRUE.equals(redis.opsForValue().setIfAbsent(key(email), code, cooldown));
    }

    @Override
    public boolean compareAndRemove(String email, String code) {
        Long removed = redis.execute(COMPARE_AND_REMOVE, List.of(key(email)), code);
        return removed != null && removed > 0;
    }

    @Override
    public Duration cooldownRemaining(String email) {
        Long ttl = redis.getExpire(key(email));
        return ttl == null || ttl <= 0 ? Duration.ZERO : Duration.ofSeconds(ttl);
    }

    private static String key(String email) {
        // 邮箱已由 domain 的 UserIdentity 归一；存储只负责拼键，不再重复业务规则
        return PREFIX + email;
    }
}
