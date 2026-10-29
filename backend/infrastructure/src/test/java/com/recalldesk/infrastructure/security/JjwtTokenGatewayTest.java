package com.recalldesk.infrastructure.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

import com.recalldesk.domain.exception.users.InvalidTokenException;
import com.recalldesk.domain.users.AuthPrincipal;
import com.recalldesk.domain.users.PrincipalType;
import java.time.Duration;
import java.time.Instant;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

class JjwtTokenGatewayTest {

    private static final String SECRET = "0123456789abcdef0123456789abcdef";
    private static final AuthPrincipal PRINCIPAL = new AuthPrincipal("user-1", "alice", PrincipalType.ACCESS);

    private StringRedisTemplate redis;
    private ValueOperations<String, String> values;
    private JjwtTokenGateway gateway;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        redis = mock(StringRedisTemplate.class);
        values = mock(ValueOperations.class);
        given(redis.opsForValue()).willReturn(values);
        // 默认没有吊销记录（get 返回 null），吊销相关的用例各自打桩
        gateway = new JjwtTokenGateway(SECRET, Duration.ofMinutes(30), Duration.ofDays(14), redis);
    }

    @Test
    @DisplayName("发出来的 access 只有按 ACCESS 要求时才验得过")
    void roundTripsAccess() {
        String token = gateway.issueAccessToken(PRINCIPAL);

        assertThat(gateway.verify(token, PrincipalType.ACCESS)).isEqualTo(PRINCIPAL);
        // 类型由调用方指定：拿 access 去换令牌这条路要堵住
        assertThatThrownBy(() -> gateway.verify(token, PrincipalType.REFRESH))
                .isInstanceOf(InvalidTokenException.class);
    }

    @Test
    @DisplayName("refresh 令牌不能当 access 用")
    void refreshTokenIsNotAnAccessToken() {
        String token = gateway.issueRefreshToken(new AuthPrincipal("user-1", "alice", PrincipalType.REFRESH));

        assertThat(gateway.verify(token, PrincipalType.REFRESH).userId()).isEqualTo("user-1");
        assertThatThrownBy(() -> gateway.verify(token, PrincipalType.ACCESS)).isInstanceOf(InvalidTokenException.class);
    }

    @Test
    @DisplayName("两类令牌各自的 TTL 独立生效")
    void ttlsArePerType() {
        JjwtTokenGateway expired =
                new JjwtTokenGateway(SECRET, Duration.ofMillis(-1000), Duration.ofMillis(-1000), redis);
        String stale = expired.issueAccessToken(PRINCIPAL);

        assertThatThrownBy(() -> gateway.verify(stale, PrincipalType.ACCESS)).isInstanceOf(InvalidTokenException.class);
    }

    @Test
    @DisplayName("换密钥、改一个字符、给 null——都是同一个无效令牌，不区分原因")
    void rejectsAnythingUnverifiable() {
        String token = gateway.issueAccessToken(PRINCIPAL);
        JjwtTokenGateway other = new JjwtTokenGateway(
                "fedcba9876543210fedcba9876543210", Duration.ofMinutes(30), Duration.ofDays(1), redis);

        assertThatThrownBy(() -> other.verify(token, PrincipalType.ACCESS)).isInstanceOf(InvalidTokenException.class);
        assertThatThrownBy(() -> gateway.verify(token + "x", PrincipalType.ACCESS))
                .isInstanceOf(InvalidTokenException.class);
        assertThatThrownBy(() -> gateway.verify("not.a.jwt", PrincipalType.ACCESS))
                .isInstanceOf(InvalidTokenException.class);
        assertThatThrownBy(() -> gateway.verify(null, PrincipalType.ACCESS)).isInstanceOf(InvalidTokenException.class);
    }

    @Test
    @DisplayName("密钥没配或太短就构造失败：宁可起不来，也不要退化成不验签")
    void refusesWeakSecret() {
        assertThatThrownBy(() -> new JjwtTokenGateway("", Duration.ofMinutes(30), Duration.ofDays(1), redis))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("未配置");
        assertThatThrownBy(() -> new JjwtTokenGateway("too-short", Duration.ofMinutes(30), Duration.ofDays(1), redis))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("32");
    }

    @Test
    @DisplayName("access 与 refresh 是两张不同的令牌，即使主体相同")
    void accessAndRefreshDiffer() {
        AuthPrincipal refreshPrincipal = new AuthPrincipal("user-1", "alice", PrincipalType.REFRESH);
        String access = gateway.issueAccessToken(PRINCIPAL);
        String refresh = gateway.issueRefreshToken(refreshPrincipal);

        assertThat(access).isNotEqualTo(refresh);
        assertThat(gateway.verify(refresh, PrincipalType.REFRESH).type()).isEqualTo(PrincipalType.REFRESH);
    }

    @Test
    @DisplayName("登出：吊销时间点晚于签发时刻的令牌，验签通过也不认")
    void logoutRevokesEarlierTokens() {
        String token = gateway.issueAccessToken(PRINCIPAL);
        given(values.get("auth:revoked-before:user-1"))
                .willReturn(String.valueOf(Instant.now().plusSeconds(60).getEpochSecond()));

        assertThatThrownBy(() -> gateway.verify(token, PrincipalType.ACCESS))
                .isInstanceOf(InvalidTokenException.class)
                .hasMessageContaining("登出");
    }

    @Test
    @DisplayName("吊销时间点早于签发时刻（登出后重新登录）：照常验得过")
    void tokensIssuedAfterLogoutStillVerify() {
        String token = gateway.issueAccessToken(PRINCIPAL);
        given(values.get("auth:revoked-before:user-1"))
                .willReturn(String.valueOf(Instant.now().minusSeconds(60).getEpochSecond()));

        assertThat(gateway.verify(token, PrincipalType.ACCESS)).isEqualTo(PRINCIPAL);
    }

    @Test
    @DisplayName("登出写的是该用户的秒级时间点，TTL 取 refresh 寿命")
    void revokeWritesSecondsWithRefreshTtl() {
        Instant before = Instant.now();

        gateway.revoke("user-1");

        ArgumentCaptor<String> value = ArgumentCaptor.forClass(String.class);
        verify(values).set(eq("auth:revoked-before:user-1"), value.capture(), eq(Duration.ofDays(14)));
        // 秒而不是毫秒：存毫秒会把「登出同一秒内重新登录」的令牌误判成已吊销
        assertThat(Long.parseLong(value.getValue()))
                .isBetween(before.getEpochSecond(), Instant.now().getEpochSecond());
    }

    @Test
    @DisplayName("吊销时间点读不到（Redis 抖动）：按未吊销处理，不把故障放大成全站 401")
    void readFailureFailsOpen() {
        String token = gateway.issueAccessToken(PRINCIPAL);
        given(values.get(any())).willThrow(new IllegalStateException("connection reset"));

        assertThat(gateway.verify(token, PrincipalType.ACCESS)).isEqualTo(PRINCIPAL);
    }
}
