package com.recalldesk.infrastructure.ratelimit;

import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

/**
 * 注册/登录/刷新的桶：按客户端 IP，5 个令牌、每 10 秒回填 1 个。
 *
 * 比接口那个狠得多：凭证接口失败一次就能判断口令对不对，几十次尝试等于把登录页
 * 交给别人当爆破工具。
 */
@Component
public class PerCredentialRateLimiter extends RedisTokenBucket {

    public PerCredentialRateLimiter(StringRedisTemplate redis) {
        super(redis);
    }

    @Override
    protected int capacity() {
        return 5;
    }

    @Override
    protected double refillPerSecond() {
        return 0.1;
    }
}
