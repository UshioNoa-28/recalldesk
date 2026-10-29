package com.recalldesk.infrastructure.security;

import com.recalldesk.domain.exception.users.InvalidTokenException;
import com.recalldesk.domain.port.auth.TokenGateway;
import com.recalldesk.domain.users.AuthPrincipal;
import com.recalldesk.domain.users.PrincipalType;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.Date;
import java.util.Locale;
import javax.crypto.SecretKey;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;

/**
 * jjwt + HS256 的令牌适配器（对称签名：一个进程自己发自己验，没有多方验公钥的需求）。
 *
 * 这一层是唯一认识 JWT 形状的地方：claim 名、算法、TTL 都关在这里，端口两端只走
 * {@link AuthPrincipal} 和字符串。ttl 按类型取，所以「refresh 比 access 长」这件事
 * 不可能被调用方写反。
 *
 * 登出吊销也在这里：令牌本来就带着 {@code iat}，一个用户一个 Redis 键存「吊销时间点」，
 * 验签时顺手比一次即可——不需要 jti 名单，也不需要逐张记。键的 TTL 取 refresh 的最长寿命：
 * 所有「早于时间点签发」的令牌都过期之后这个键就没意义了，交给 Redis 自己收。
 * 读失败按未吊销处理（放行 + WARN）：Redis 抖动不该让全站 401。
 */
public class JjwtTokenGateway implements TokenGateway {

    private static final String CLAIM_TYPE = "typ";
    private static final String CLAIM_USERNAME = "name";
    private static final String REVOKED_BEFORE_PREFIX = "auth:revoked-before:";
    private static final Logger log = LoggerFactory.getLogger(JjwtTokenGateway.class);

    private final SecretKey key;
    private final Duration accessTtl;
    private final Duration refreshTtl;
    private final StringRedisTemplate redis;

    public JjwtTokenGateway(
            String secret, Duration accessTtl, Duration refreshTtl, StringRedisTemplate redis) {
        if (secret == null || secret.isBlank()) {
            throw new IllegalStateException("JWT secret 未配置：没有它无法签发令牌，也不该退化成「不设密钥就不验」");
        }
        byte[] raw = secret.getBytes(StandardCharsets.UTF_8);
        if (raw.length < 32) {
            // jjwt 对短于 256 bit 的 HMAC 密钥直接抛 WeakKeyException，先在这儿说人话
            throw new IllegalStateException("JWT secret 至少需要 32 字节，当前 " + raw.length + " 字节");
        }
        this.key = Keys.hmacShaKeyFor(raw);
        this.accessTtl = accessTtl;
        this.refreshTtl = refreshTtl;
        this.redis = redis;
    }

    @Override
    public String issueAccessToken(AuthPrincipal principal) {
        return issue(principal, accessTtl);
    }

    @Override
    public String issueRefreshToken(AuthPrincipal principal) {
        return issue(principal, refreshTtl);
    }

    @Override
    public AuthPrincipal verify(String token, PrincipalType expected) {
        Claims claims = parse(token);
        String type = claims.get(CLAIM_TYPE, String.class);
        if (!label(expected).equals(type)) {
            throw new InvalidTokenException("令牌类型是 " + type + "，此处只接受 " + label(expected));
        }
        String userId = claims.getSubject();
        if (revoked(userId, claims.getIssuedAt().toInstant())) {
            throw new InvalidTokenException("令牌已登出");
        }
        return new AuthPrincipal(userId, claims.get(CLAIM_USERNAME, String.class), expected);
    }

    @Override
    public void revoke(String userId) {
        // 存秒而不是毫秒：JWT 的 iat 本来就是秒粒度（NumericDate），存毫秒会把登出
        // 同一秒内重新登录签发的令牌误判成「早于吊销时间点」
        redis.opsForValue().set(
                REVOKED_BEFORE_PREFIX + userId,
                String.valueOf(Instant.now().getEpochSecond()),
                refreshTtl);
    }

    private boolean revoked(String userId, Instant issuedAt) {
        Instant cutoff;
        try {
            String value = redis.opsForValue().get(REVOKED_BEFORE_PREFIX + userId);
            cutoff = value == null ? Instant.EPOCH : Instant.ofEpochSecond(Long.parseLong(value));
        } catch (RuntimeException exc) {
            log.warn("读取登出时间点失败，按未吊销处理: user={} err={}", userId, exc.toString());
            return false;
        }
        // 严格小于、按秒比较：登出那一秒内签发的令牌仍然算「不早于」
        return issuedAt.getEpochSecond() < cutoff.getEpochSecond();
    }

    private String issue(AuthPrincipal principal, Duration ttl) {
        Instant now = Instant.now();
        return Jwts.builder()
                .subject(principal.userId())
                .claim(CLAIM_TYPE, label(principal.type()))
                .claim(CLAIM_USERNAME, principal.username())
                .issuedAt(Date.from(now))
                .expiration(Date.from(now.plus(ttl)))
                .signWith(key)
                .compact();
    }

    /** claim 里的类型用小写串（access / refresh），别把 Java 枚举名泄漏成对外契约。 */
    private static String label(PrincipalType type) {
        return type.name().toLowerCase(Locale.ROOT);
    }

    private Claims parse(String token) {
        try {
            return Jwts.parser().verifyWith(key).build().parseSignedClaims(token).getPayload();
        } catch (JwtException | IllegalArgumentException exc) {
            // 签名不符 / 过期 / 结构坏 / 传了 null，对外同一个 401，不区分原因给调用方看
            throw new InvalidTokenException(exc.getMessage());
        }
    }
}
