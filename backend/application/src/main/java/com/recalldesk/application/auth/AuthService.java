package com.recalldesk.application.auth;

import com.recalldesk.application.auth.dto.Authenticated;
import com.recalldesk.domain.exception.users.BadCredentialsException;
import com.recalldesk.domain.exception.users.EmailTakenException;
import com.recalldesk.domain.exception.users.InvalidTokenException;
import com.recalldesk.domain.exception.users.UsernameTakenException;
import com.recalldesk.domain.port.auth.PasswordHasher;
import com.recalldesk.domain.port.auth.TokenGateway;
import com.recalldesk.domain.port.ops.UnitOfWork;
import com.recalldesk.domain.port.persistence.UserRepository;
import com.recalldesk.domain.users.AuthPrincipal;
import com.recalldesk.domain.users.PrincipalType;
import com.recalldesk.domain.users.User;
import com.recalldesk.domain.users.UserIdentity;
import java.time.Instant;
import java.util.Optional;
import java.util.UUID;
import org.springframework.stereotype.Component;

/**
 * 账号用例：注册、登录、刷新、登出。
 *
 * 三条规矩在这里定死，不留给调用方：用户名与邮箱入库前一律归一（见 {@link UserIdentity}，
 * 于是唯一性自然大小写不敏感）、口令只以 PBKDF2 散列出库、令牌里的主体只有 id 与用户名。
 *
 * 形状校验（非空、长度、邮箱格式）在 web 层的 DTO 注解上；这里只处理要查状态的业务规则。
 */
@Component
public class AuthService {

    private final UserRepository users;
    private final PasswordHasher hasher;
    private final TokenGateway tokens;
    private final EmailCodeService emailCodes;
    private final UnitOfWork unitOfWork;

    public AuthService(
            UserRepository users,
            PasswordHasher hasher,
            TokenGateway tokens,
            EmailCodeService emailCodes,
            UnitOfWork unitOfWork) {
        this.users = users;
        this.hasher = hasher;
        this.tokens = tokens;
        this.emailCodes = emailCodes;
        this.unitOfWork = unitOfWork;
    }

    /**
     * 注册：归一 → 查重 → 验邮箱码 → 散列 → 落库 → 直接发一对令牌。
     *
     * 顺序是有讲究的：用户名/邮箱占用这些「免费就能判」的先判完，最后才消费验证码——
     * 否则用户填了个已被占用的用户名，码先被烧掉，改完名字还得等下一封邮件。
     * 它挡不住并发，真正的裁决仍是库里的两个唯一索引（见 MyBatisUserRepository.add）。
     */
    public Authenticated register(String rawUsername, String password, String rawEmail, String code) {
        String username = UserIdentity.of(rawUsername).value();
        String email = UserIdentity.of(rawEmail).value();
        if (users.findByUsername(username).isPresent()) {
            throw new UsernameTakenException(username);
        }
        if (users.findByEmail(email).isPresent()) {
            throw new EmailTakenException(email);
        }
        emailCodes.requireValidCode(email, code);
        User user = new User(
                UUID.randomUUID().toString(), username, hasher.hash(password), email, Instant.now());
        unitOfWork.execute(() -> users.add(user));
        return issue(user);
    }

    /**
     * 登录：identifier 先按用户名查，查不到再按邮箱查。
     * 用户不存在与口令不对都给 BadCredentialsException，调用方无从区分。
     */
    public Authenticated login(String identifier, String password) {
        User user = findByIdentifier(identifier)
                .orElseThrow(BadCredentialsException::new);
        if (!hasher.matches(password, user.passwordHash())) {
            throw new BadCredentialsException();
        }
        return issue(user);
    }

    /**
     * 刷新：只接受 refresh 类型的令牌，换新的一对（access 短命的意义就在于它不换自己）。
     *
     * 登出吊销不用在这里写：{@code tokens.verify} 自己会拒掉登出之前签发的令牌。
     */
    public Authenticated refresh(String refreshToken) {
        AuthPrincipal principal = tokens.verify(refreshToken, PrincipalType.REFRESH);
        User user = users.get(principal.userId())
                .orElseThrow(() -> new InvalidTokenException("账号已不存在"));
        return issue(user);
    }

    /**
     * 登出：该用户此前签发的 access 与 refresh 全部作废，之后必须重新登录。
     *
     * 语义是「该用户所有设备一起退出」；想只退当前设备就得按 jti 逐张记，那是另一套东西。
     */
    public void logout(String userId) {
        tokens.revoke(userId);
    }

    /** 先用户名后邮箱：用户名不再限制字符，含 {@code @} 的用户名也得能登录。 */
    private Optional<User> findByIdentifier(String rawIdentifier) {
        String identifier = UserIdentity.of(rawIdentifier).value();
        return users.findByUsername(identifier).or(() -> users.findByEmail(identifier));
    }

    private Authenticated issue(User user) {
        AuthPrincipal principal = new AuthPrincipal(user.id(), user.username(), PrincipalType.ACCESS);
        AuthPrincipal refreshPrincipal = new AuthPrincipal(user.id(), user.username(), PrincipalType.REFRESH);
        return new Authenticated(
                tokens.issueAccessToken(principal),
                tokens.issueRefreshToken(refreshPrincipal),
                user);
    }
}