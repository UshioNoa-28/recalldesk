package com.recalldesk.application.auth;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.recalldesk.application.FakeTransactionManager;
import com.recalldesk.application.auth.dto.Authenticated;
import com.recalldesk.domain.port.auth.EmailCodeStore;
import com.recalldesk.domain.port.auth.EmailSender;
import com.recalldesk.domain.port.auth.PasswordHasher;
import com.recalldesk.domain.port.auth.TokenGateway;
import com.recalldesk.domain.port.persistence.UserRepository;
import com.recalldesk.domain.users.AuthPrincipal;
import com.recalldesk.domain.exception.users.BadCredentialsException;
import com.recalldesk.domain.exception.users.EmailCodeInvalidException;
import com.recalldesk.domain.exception.users.EmailCodeTooFrequentException;
import com.recalldesk.domain.exception.users.EmailTakenException;
import com.recalldesk.domain.exception.users.InvalidTokenException;
import com.recalldesk.domain.users.PrincipalType;
import com.recalldesk.domain.users.User;
import com.recalldesk.domain.users.UserIdentity;
import com.recalldesk.domain.exception.users.UsernameTakenException;
import java.time.Instant;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class AuthServiceTest {

    private static final String GOOD_PASSWORD = "s3cret-pass";

    /** 可预期的假散列：把口令当键，验证「比对读的是存进去的那份」。 */
    private static final class FakeHasher implements PasswordHasher {
        @Override
        public String hash(String plaintext) {
            return "hashed:" + plaintext;
        }

        @Override
        public boolean matches(String plaintext, String encoded) {
            return ("hashed:" + plaintext).equals(encoded);
        }
    }

    private static final class FakeUsers implements UserRepository {
        final Map<String, User> byUsername = new LinkedHashMap<>();
        boolean failNextAdd;

        @Override
        public void add(User user) {
            if (failNextAdd) {
                throw new UsernameTakenException(user.username());
            }
            byUsername.put(user.username(), user);
        }

        @Override
        public Optional<User> findByUsername(String username) {
            return Optional.ofNullable(byUsername.get(username));
        }

        @Override
        public Optional<User> findByEmail(String email) {
            return byUsername.values().stream().filter(u -> email.equals(u.email())).findFirst();
        }

        @Override
        public Optional<User> get(String userId) {
            return byUsername.values().stream().filter(user -> user.id().equals(userId)).findFirst();
        }
    }

    /**
     * 假网关：令牌按字符串存主体，吊销记时间点——登出吊销的比较本来就是网关的语义，
     * 这里照它约定的形状假一份，业务侧才能测到「刷新被拒」。
     */
    private static final class FakeTokens implements TokenGateway {
        private record Issued(AuthPrincipal principal, Instant issuedAt) {}

        final Map<String, Issued> issued = new LinkedHashMap<>();
        final Map<String, Instant> revokedBefore = new LinkedHashMap<>();
        int counter;

        @Override
        public String issueAccessToken(AuthPrincipal principal) {
            return issue("access", principal);
        }

        @Override
        public String issueRefreshToken(AuthPrincipal principal) {
            return issue("refresh", principal);
        }

        @Override
        public AuthPrincipal verify(String token, PrincipalType expected) {
            Issued issued = this.issued.get(token);
            if (issued == null || issued.principal().type() != expected) {
                throw new InvalidTokenException("假件里没这张或类型不对");
            }
            Instant cutoff = revokedBefore.get(issued.principal().userId());
            if (cutoff != null && issued.issuedAt().isBefore(cutoff)) {
                throw new InvalidTokenException("令牌已登出");
            }
            return issued.principal();
        }

        @Override
        public void revoke(String userId) {
            revokedBefore.put(userId, Instant.now());
        }

        private String issue(String kind, AuthPrincipal principal) {
            String token = kind + "-" + (++counter);
            issued.put(token, new Issued(principal, Instant.now()));
            return token;
        }
    }

    /** 假验证码存储：码就记在内存里，验过即删。 */
    private static final class FakeEmailCodes implements EmailCodeStore {
        final Map<String, String> codes = new LinkedHashMap<>();

        @Override
        public boolean reserve(String email, String code, Duration cooldown) {
            return codes.putIfAbsent(email, code) == null;
        }

        @Override
        public boolean compareAndRemove(String email, String code) {
            return codes.remove(email, code);
        }

        @Override
        public Duration cooldownRemaining(String email) {
            return Duration.ZERO;
        }
    }

    private static final class FakeSender implements EmailSender {
        final List<String> sent = new ArrayList<>();
        RuntimeException failWith;

        @Override
        public void sendVerificationCode(String email, String code, long validMinutes) {
            if (failWith != null) {
                throw failWith;
            }
            sent.add(email + ":" + code);
        }
    }

    private final FakeUsers users = new FakeUsers();
    private final FakeHasher hasher = new FakeHasher();
    private final FakeTokens tokens = new FakeTokens();
    private final FakeEmailCodes emailCodes = new FakeEmailCodes();
    private final FakeSender sender = new FakeSender();
    private final FakeTransactionManager txManager = new FakeTransactionManager();
    private final EmailCodeService emailCodeService =
            new EmailCodeService(emailCodes, sender, Duration.ofMinutes(10));
    private final AuthService service = new AuthService(
            users, hasher, tokens, emailCodeService, txManager.unitOfWork());

    /** 注册的常规入口：先备好一枚码，再带上去注册。 */
    private Authenticated register(String username, String password, String email) {
        emailCodes.codes.put(UserIdentity.of(email).value(), "123456");
        return service.register(username, password, email, "123456");
    }

    @Test
    @DisplayName("注册：用户名转小写入库、口令只存散列、返回可直接用的一对令牌")
    void registerCanonicalizesAndIssues() {
        Authenticated result = register("  Alice.IN  ", GOOD_PASSWORD, "Alice@Example.com");

        assertThat(result.user().username()).isEqualTo("alice.in");
        assertThat(result.user().email()).isEqualTo("alice@example.com");
        assertThat(result.user().passwordHash()).isEqualTo("hashed:" + GOOD_PASSWORD);
        assertThat(result.accessToken()).startsWith("access-");
        assertThat(result.refreshToken()).startsWith("refresh-");
        assertThat(txManager.commits).isEqualTo(1);
        assertThat(users.byUsername).containsKey("alice.in");
    }

    @Test
    @DisplayName("占用冲突原样上抛并回滚（唯一索引才是最终裁决，预检挡不住并发）")
    void registerSurfacesConflict() {
        register("alice", GOOD_PASSWORD, "alice@example.com");
        // 模拟并发：预检时库里还没有，插入时唯一索引才说话
        users.failNextAdd = true;
        emailCodes.codes.put("bob@example.com", "123456");

        assertThatThrownBy(() -> service.register("bob", GOOD_PASSWORD, "bob@example.com", "123456"))
                .isInstanceOf(UsernameTakenException.class);
        assertThat(txManager.rollbacks).isEqualTo(1);
    }

    @Test
    @DisplayName("登录成功给同一形状的结果")
    void loginHappyPath() {
        register("Alice", GOOD_PASSWORD, "alice@example.com");

        Authenticated result = service.login("alice", GOOD_PASSWORD);

        assertThat(result.user().username()).isEqualTo("alice");
        assertThat(result.accessToken()).isNotBlank();
    }

    @Test
    @DisplayName("口令错与用户不存在给同一个异常")
    void loginIsIndistinguishable() {
        register("alice", GOOD_PASSWORD, "alice@example.com");

        assertThatThrownBy(() -> service.login("alice", "错口令")).isInstanceOf(BadCredentialsException.class);
        assertThatThrownBy(() -> service.login("nobody", GOOD_PASSWORD)).isInstanceOf(BadCredentialsException.class);
    }

    @Test
    @DisplayName("登录标识可以填邮箱：含 @ 的按邮箱查，大小写不敏感")
    void loginAcceptsEmailIdentifier() {
        register("alice", GOOD_PASSWORD, "Alice@Example.com");

        assertThat(service.login("ALICE@example.com", GOOD_PASSWORD).user().username()).isEqualTo("alice");
    }

    @Test
    @DisplayName("登录标识先按用户名解析：用户名里带 @ 也能登录")
    void loginResolvesUsernameBeforeEmail() {
        register("a@b", GOOD_PASSWORD, "a@example.com");

        assertThat(service.login("a@b", GOOD_PASSWORD).user().username()).isEqualTo("a@b");
    }

    @Test
    @DisplayName("注册：邮箱已被占用时报邮箱重复（不是用户名重复，用户知道该改哪一栏）")
    void registerRejectsTakenEmail() {
        register("alice", GOOD_PASSWORD, "same@example.com");
        emailCodes.codes.put("same@example.com", "123456");

        assertThatThrownBy(() -> service.register("bob", GOOD_PASSWORD, "same@example.com", "123456"))
                .isInstanceOf(EmailTakenException.class);
    }

    @Test
    @DisplayName("注册：验证码不对/没发过/已被用过一律同一个异常")
    void registerRejectsBadCode() {
        assertThatThrownBy(() -> service.register("alice", GOOD_PASSWORD, "a@example.com", "000000"))
                .isInstanceOf(EmailCodeInvalidException.class);

        // 用过一次就作废：同一枚码不能再注册第二个账号（邮箱已被占用是另一条分支，这里换新邮箱）
        emailCodes.codes.put("a@example.com", "123456");
        service.register("alice", GOOD_PASSWORD, "a@example.com", "123456");
        assertThatThrownBy(() -> service.register("bob", GOOD_PASSWORD, "b@example.com", "123456"))
                .isInstanceOf(EmailCodeInvalidException.class);
        // 码与邮箱绑定：a 的码拿去给 c 用不行
        emailCodes.codes.put("c@example.com", "654321");
        assertThatThrownBy(() -> service.register("carol", GOOD_PASSWORD, "c@example.com", "123456"))
                .isInstanceOf(EmailCodeInvalidException.class);
    }

    @Test
    @DisplayName("注册：先判完免费的那些（用户名/邮箱占用）再验码，不白烧用户的码")
    void registerChecksCheapConditionsBeforeConsumingCode() {
        register("alice", GOOD_PASSWORD, "alice@example.com");
        emailCodes.codes.put("bob@example.com", "123456");

        assertThatThrownBy(() -> service.register("alice", GOOD_PASSWORD, "bob@example.com", "123456"))
                .isInstanceOf(UsernameTakenException.class);
        // 码还在：改个用户名就能继续用
        assertThat(emailCodes.codes).containsEntry("bob@example.com", "123456");
    }

    @Test
    @DisplayName("发码：冷却期内再要一次就 429 语义，且不会顶掉前一封")
    void sendCodeRespectsCooldown() {
        emailCodes.codes.put("a@example.com", "111111");

        assertThatThrownBy(() -> emailCodeService.sendCode("a@example.com"))
                .isInstanceOf(EmailCodeTooFrequentException.class);
        assertThat(emailCodes.codes).containsEntry("a@example.com", "111111");
    }

    @Test
    @DisplayName("发码：邮箱归一为小写；发信失败要把冷却位还回去")
    void sendCodeNormalizesAndReleasesOnFailure() {
        emailCodeService.sendCode("  A@Example.com ");
        assertThat(sender.sent).hasSize(1);
        assertThat(sender.sent.get(0)).startsWith("a@example.com:");

        emailCodes.codes.clear();
        sender.sent.clear();
        sender.failWith = new IllegalStateException("smtp down");
        assertThatThrownBy(() -> emailCodeService.sendCode("b@example.com"))
                .isInstanceOf(IllegalStateException.class);
        assertThat(emailCodes.codes).doesNotContainKey("b@example.com");
    }

    @Test
    @DisplayName("刷新只认 refresh 令牌，且账号已不在时算无效令牌")
    void refreshChecksTypeAndMembership() {
        Authenticated registered = register("alice", GOOD_PASSWORD, "alice@example.com");

        assertThatThrownBy(() -> service.refresh(registered.accessToken()))
                .isInstanceOf(InvalidTokenException.class);
        assertThat(service.refresh(registered.refreshToken()).user().username()).isEqualTo("alice");

        users.byUsername.clear();
        assertThatThrownBy(() -> service.refresh(registered.refreshToken())).isInstanceOf(InvalidTokenException.class);
    }

    @Test
    @DisplayName("令牌主体只带 id 与用户名——不带走散列")
    void tokensCarryMinimalPrincipal() {
        register("alice", GOOD_PASSWORD, "alice@example.com");
        AuthPrincipal principal = tokens.verify("access-1", PrincipalType.ACCESS);

        assertThat(principal.username()).isEqualTo("alice");
        assertThat(principal.type()).isEqualTo(PrincipalType.ACCESS);
        assertThat(principal.userId()).isNotBlank();
        assertThat(users.byUsername.get("alice").createdAt()).isBefore(Instant.now().plusSeconds(1));
    }

    @Test
    @DisplayName("登出：此前签发的 refresh 立刻换不出新令牌")
    void logoutRevokesEarlierRefreshTokens() {
        Authenticated registered = register("alice", GOOD_PASSWORD, "alice@example.com");

        service.logout(registered.user().id());

        assertThatThrownBy(() -> service.refresh(registered.refreshToken()))
                .isInstanceOf(InvalidTokenException.class)
                .hasMessageContaining("登出");
    }

    @Test
    @DisplayName("登出后重新登录：新令牌晚于吊销点，照常可用")
    void tokensIssuedAfterLogoutStillWork() {
        Authenticated first = register("alice", GOOD_PASSWORD, "alice@example.com");
        service.logout(first.user().id());

        Authenticated second = service.login("alice", GOOD_PASSWORD);

        assertThat(service.refresh(second.refreshToken()).user().username()).isEqualTo("alice");
    }

    @Test
    @DisplayName("吊销只作用于该用户：登出 alice 不影响 bob 的令牌")
    void logoutIsPerUser() {
        Authenticated alice = register("alice", GOOD_PASSWORD, "alice@example.com");
        Authenticated bob = register("bob", GOOD_PASSWORD, "bob@example.com");

        service.logout(alice.user().id());

        assertThatThrownBy(() -> service.refresh(alice.refreshToken()))
                .isInstanceOf(InvalidTokenException.class);
        assertThat(service.refresh(bob.refreshToken()).user().username()).isEqualTo("bob");
    }
}
