package com.recalldesk.domain.port.ops;

/**
 * 令牌桶限流：按桶名取一个令牌。
 *
 * 桶名由调用方给（用户 id、客户端 IP），端口不认识身份；容量与回填速率归实现自己，
 * 换一种限流算法就是换一个实现注入进来。
 */
public interface RateLimiter {

    /** 取一个令牌。 */
    Decision acquire(String bucket);

    /** 一次取令牌的结果。 */
    record Decision(
            /** 放不放行。 */
            boolean allowed,
            /** 桶容量，回给调用方放进 X-RateLimit-Limit。 */
            int limit,
            /** 取完还剩几个，放进 X-RateLimit-Remaining。 */
            int remaining,
            /** 被拒时等几秒再来，放进 Retry-After；放行时为 0。 */
            long retryAfterSeconds) {

        public static Decision allowed(int limit, int remaining) {
            return new Decision(true, limit, Math.max(0, remaining), 0);
        }

        public static Decision rejected(int limit, long retryAfterSeconds) {
            return new Decision(false, limit, 0, Math.max(1, retryAfterSeconds));
        }
    }
}
