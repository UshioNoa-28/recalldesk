package com.recalldesk.infrastructure.ratelimit;

import static org.assertj.core.api.Assertions.assertThat;

import com.recalldesk.domain.port.ops.RateLimiter;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;

/**
 * 真 Redis 上的令牌桶（手动拉起：{@code -Dtest=RedisTokenBucketIT}，需本机 6380）。
 *
 * 单测测不到的是脚本本身：回填算术、扣减、ceil 出来的等待秒数，以及「读桶 + 算 + 写回」
 * 是否真的原子。这些一旦写错，表现是限流数字对不上、或者并发下放过双份。
 *
 * 桶名带 uuid，用例结束删键：这台 Redis 与任务队列共用，不该留测试残渣。
 */
class RedisTokenBucketIT {

    private static LettuceConnectionFactory factory;
    private static StringRedisTemplate redis;
    /** 容量 3、每秒回填 1：用例里手数得清。 */
    private static RedisTokenBucket bucket;

    @BeforeAll
    static void connect() {
        factory = new LettuceConnectionFactory("127.0.0.1", 6380);
        factory.afterPropertiesSet();
        redis = new StringRedisTemplate(factory);
        redis.afterPropertiesSet();
        bucket = new RedisTokenBucket(redis) {
            @Override
            protected int capacity() {
                return 3;
            }

            @Override
            protected double refillPerSecond() {
                return 1;
            }
        };
    }

    @AfterAll
    static void close() {
        factory.destroy();
    }

    private static String fresh(String tag) {
        String name = "it:" + tag + ":" + UUID.randomUUID();
        redis.delete("ratelimit:" + name);
        return name;
    }

    @Test
    @DisplayName("满桶扣到空：前 3 次放行、余量数到 0，第 4 次拒并给出等待秒数")
    void drainsExactlyCapacity() {
        String name = fresh("drain");

        assertThat(bucket.acquire(name).remaining()).isEqualTo(2);
        assertThat(bucket.acquire(name).remaining()).isEqualTo(1);
        assertThat(bucket.acquire(name).remaining()).isZero();

        RateLimiter.Decision fourth = bucket.acquire(name);
        assertThat(fourth.allowed()).isFalse();
        assertThat(fourth.retryAfterSeconds()).isEqualTo(1); // 速率 1/秒，等 1 秒即可
    }

    @Test
    @DisplayName("等一秒回填一个：被拒之后 sleep 1s 就能重新拿到一个")
    void refillsOnePerSecond() throws InterruptedException {
        String name = fresh("refill");
        for (int i = 0; i < 3; i++) {
            bucket.acquire(name);
        }
        assertThat(bucket.acquire(name).allowed()).isFalse();

        Thread.sleep(1100);

        assertThat(bucket.acquire(name).allowed()).isTrue();
    }

    @Test
    @DisplayName("并发只放行容量那么多次：读-算-写回是原子的")
    void concurrentAcquiresNeverExceedCapacity() throws InterruptedException {
        String name = fresh("concurrent");
        int threads = 12;
        CountDownLatch start = new CountDownLatch(1);
        CountDownLatch done = new CountDownLatch(threads);
        AtomicInteger allowed = new AtomicInteger();
        List<Thread> workers = new ArrayList<>();
        for (int i = 0; i < threads; i++) {
            Thread worker = new Thread(() -> {
                try {
                    start.await();
                    if (bucket.acquire(name).allowed()) {
                        allowed.incrementAndGet();
                    }
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                } finally {
                    done.countDown();
                }
            });
            workers.add(worker);
            worker.start();
        }
        start.countDown();
        done.await();

        assertThat(allowed.get()).isEqualTo(3);
    }

    @Test
    @DisplayName("桶有闲置 TTL：冷桶不会永久占着 Redis")
    void bucketCarriesTtl() {
        String name = fresh("ttl");
        bucket.acquire(name);

        assertThat(redis.getExpire("ratelimit:" + name)).isPositive();
    }
}
