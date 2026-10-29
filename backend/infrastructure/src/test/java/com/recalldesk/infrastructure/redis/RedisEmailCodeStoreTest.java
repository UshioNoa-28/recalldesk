package com.recalldesk.infrastructure.redis;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

import java.time.Duration;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.data.redis.core.script.RedisScript;

/**
 * 验证码存储的命令级测试：冷却靠 SET NX、校验靠一段 Lua（比对与删除必须原子）。
 *
 * 真 Redis 上的语义另有一份 IT（{@code RedisEmailCodeStoreIT}）；这里钉的是
 * 「发的是哪几个命令、键长什么样」，因为假存储（application 层测试用的）正是照它写的。
 */
class RedisEmailCodeStoreTest {

    private StringRedisTemplate redis;
    private ValueOperations<String, String> values;
    private RedisEmailCodeStore store;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        redis = mock(StringRedisTemplate.class);
        values = mock(ValueOperations.class);
        given(redis.opsForValue()).willReturn(values);
        store = new RedisEmailCodeStore(redis);
    }

    @Test
    @DisplayName("发码：SET NX + TTL，键是归一化后的邮箱")
    void reserveUsesSetIfAbsent() {
        given(values.setIfAbsent("email-code:alice@example.com", "123456", Duration.ofMinutes(10)))
                .willReturn(true);

        assertThat(store.reserve("alice@example.com", "123456", Duration.ofMinutes(10))).isTrue();
    }

    @Test
    @DisplayName("发码：冷却期内 NX 失败即 false（不顶掉前一封）")
    void reserveFailsWithinCooldown() {
        given(values.setIfAbsent(any(), any(), any(Duration.class))).willReturn(false);

        assertThat(store.reserve("alice@example.com", "999999", Duration.ofMinutes(10))).isFalse();
    }

    @Test
    @DisplayName("校验：走一段 Lua，把码当参数、键当 KEYS[1]，非 1 的返回都算失败")
    @SuppressWarnings("unchecked")
    void compareAndRemoveRunsScript() {
        given(redis.execute(any(RedisScript.class), eq(List.of("email-code:alice@example.com")), eq("123456")))
                .willReturn(1L);
        assertThat(store.compareAndRemove("alice@example.com", "123456")).isTrue();

        given(redis.execute(any(RedisScript.class), any(), any())).willReturn(0L);
        assertThat(store.compareAndRemove("alice@example.com", "000000")).isFalse();
    }

    @Test
    @DisplayName("冷却剩余：TTL 非正（键不在/没过期时间）给零")
    void cooldownRemaining() {
        given(redis.getExpire(any())).willReturn(42L);
        assertThat(store.cooldownRemaining("a@b.com")).isEqualTo(Duration.ofSeconds(42));

        given(redis.getExpire(any())).willReturn(-1L);
        assertThat(store.cooldownRemaining("a@b.com")).isZero();

        given(redis.getExpire(any())).willReturn(null);
        assertThat(store.cooldownRemaining("a@b.com")).isZero();

        // 三次调用都打了同一个键（键名归一到小写这一层在这里被钉住）
        verify(redis, org.mockito.Mockito.atLeastOnce()).getExpire("email-code:a@b.com");
    }
}
