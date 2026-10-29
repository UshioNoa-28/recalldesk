package com.recalldesk.infrastructure.ratelimit;

import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

/** 已认证接口的桶：按用户，30 个令牌、每秒回填 5 个。 */
@Component
public class PerUserRateLimiter extends RedisTokenBucket {

    public PerUserRateLimiter(StringRedisTemplate redis) {
        super(redis);
    }

    @Override
    protected int capacity() {
        return 30;
    }

    @Override
    protected double refillPerSecond() {
        return 5;
    }
}
