package com.recalldesk.infrastructure.ratelimit;

import com.recalldesk.domain.port.ops.RateLimiter;
import java.util.List;
import java.util.concurrent.TimeUnit;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.RedisScript;

/**
 * Redis 上的令牌桶：读桶、按流逝时间回填、扣一个、写回，全在一段 Lua 里一次跑完。
 *
 * 不用「先 GET 算再 SET」：两个并发请求会读到同一个桶、各减一，限流就形同虚设——
 * 而并发恰好是限流唯一要防的东西。也不用分布式锁：Redis 单个脚本本来就原子，
 * 加锁只是多几次往返外加一个锁过期的缺口。
 *
 * 限额由子类定：容量与回填速率是这条链路自己的事，不由调用方传、也不走配置文件。
 */
abstract class RedisTokenBucket implements RateLimiter {

    /** KEYS[1]=桶名；ARGV=容量、每秒回填、当前微秒、键闲置秒数。返回 {放行?, 余量, 重试秒}。 */
    private static final RedisScript<?> ACQUIRE = RedisScript.of(
            """
            local capacity = tonumber(ARGV[1])
            local refill = tonumber(ARGV[2])
            local now = tonumber(ARGV[3])
            local idle = tonumber(ARGV[4])
            local stored = redis.call('HMGET', KEYS[1], 'tokens', 'stamp')
            local tokens = tonumber(stored[1])
            local stamp = tonumber(stored[2])
            if tokens == nil then tokens = capacity end
            if stamp == nil then stamp = now end
            local elapsed = now - stamp
            if elapsed < 0 then elapsed = 0 end
            tokens = math.min(capacity, tokens + elapsed * refill / 1000000)
            local allowed = 0
            local wait = 0
            if tokens >= 1 then
                allowed = 1
                tokens = tokens - 1
            else
                -- 还差 (1-tokens) 个令牌 ÷ 每秒回填几个；Retry-After 是整数秒要向上取整，
                -- 给 0 等于叫对方立刻再撞一次
                wait = math.ceil((1 - tokens) / refill)
            end
            redis.call('HSET', KEYS[1], 'tokens', tokens, 'stamp', now)
            redis.call('EXPIRE', KEYS[1], idle)
            return {allowed, math.floor(tokens), wait}
            """,
            List.class);

    private final StringRedisTemplate redis;

    protected RedisTokenBucket(StringRedisTemplate redis) {
        this.redis = redis;
    }

    /** 桶能装几个令牌。 */
    protected abstract int capacity();

    /** 每秒回填几个令牌。 */
    protected abstract double refillPerSecond();

    @Override
    public Decision acquire(String bucket) {
        // bucket 作为key 总key为 ratelimit:{bucket}
        int capacity = capacity();
        // 脚本的返回类型只能声明成 List.class（RedisScript.of 没法表达 List<Long>），
        // 所以在边界上收一次：拿到 List<?>，元素按 Number 取。
        List<?> state;
        try {
            state = (List<?>) redis.execute(
                    ACQUIRE,
                    List.of("ratelimit:" + bucket),
                    String.valueOf(capacity),
                    // String.valueOf(double) 恒用小数点，不受默认 locale 影响（"0,1" 会让 Lua 的 tonumber 给 nil）
                    String.valueOf(refillPerSecond()),
                    String.valueOf(TimeUnit.MICROSECONDS.convert(System.currentTimeMillis(), TimeUnit.MILLISECONDS)),
                    // 闲置 TTL：空桶涨回满桶的时间再翻一倍，冷桶不该一直占着 Redis
                    String.valueOf(Math.max(60, secondsToFullBucket() * 2)));
        } catch (RuntimeException exc) {
            // Redis 抖动时放行：限流是保护后端的手段，不该把自己变成 503 的来源
            return Decision.allowed(capacity, capacity - 1);
        }
        if (state == null || state.size() < 3) {
            return Decision.allowed(capacity, capacity - 1);
        }
        // Redis 的整数回复在驱动里是 Long，统一走 Number 取，不依赖具体装箱类型
        boolean allowed = ((Number) state.get(0)).longValue() == 1;
        long remaining = ((Number) state.get(1)).longValue();
        return allowed
                ? Decision.allowed(capacity, (int) remaining)
                : Decision.rejected(capacity, ((Number) state.get(2)).longValue());
    }

    private long secondsToFullBucket() {
        return (long) Math.ceil(capacity() / refillPerSecond());
    }
}
