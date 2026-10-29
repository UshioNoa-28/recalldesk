package com.recalldesk.interfaces.web;

import com.recalldesk.application.auth.AuthService;
import com.recalldesk.application.auth.dto.Authenticated;
import com.recalldesk.application.auth.EmailCodeService;
import com.recalldesk.domain.port.persistence.UserRepository;
import com.recalldesk.domain.users.User;
import com.recalldesk.interfaces.security.AuthenticatedUser;
import com.recalldesk.interfaces.web.dto.AuthDtos.Credentials;
import com.recalldesk.interfaces.web.dto.AuthDtos.EmailCodeRequest;
import com.recalldesk.interfaces.web.dto.AuthDtos.RefreshRequest;
import com.recalldesk.interfaces.web.dto.AuthDtos.RegisterRequest;
import com.recalldesk.interfaces.web.dto.AuthDtos.TokenPair;
import com.recalldesk.interfaces.web.dto.AuthDtos.UserView;
import jakarta.validation.Valid;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

/**
 * 账号路由：发验证码、注册、登录、刷新、登出、我是谁。
 *
 * 发码/注册/登录/刷新是公开路径（在 {@code AuthConfiguration} 的白名单里）；
 * {@code /auth/me} 与 {@code /auth/logout} 必须带 access 令牌。
 * 形状校验在 DTO 注解上，业务规则（查重、验证码、散列）归 {@link AuthService}；
 * 出参一律重新拼一遍，领域对象里的口令散列不允许顺着 Jackson 溜出去。
 */
@RestController
public class AuthController {

    private final AuthService authService;
    private final EmailCodeService emailCodes;
    private final UserRepository users;

    public AuthController(AuthService authService, EmailCodeService emailCodes, UserRepository users) {
        this.authService = authService;
        this.emailCodes = emailCodes;
        this.users = users;
    }

    /**
     * 发一枚注册验证码：202 而不是 200，因为它只是"已受理"，真正的结果在用户邮箱里。
     *
     * 不告诉调用方"这个邮箱注册过没有"：发码接口是公开的，能枚举就等于把账号清单送出去。
     */
    @PostMapping("/auth/email-code")
    @ResponseStatus(HttpStatus.ACCEPTED)
    public Map<String, String> sendEmailCode(@Valid @RequestBody(required = false) EmailCodeRequest body) {
        if (body == null) {
            throw missingBody();
        }
        emailCodes.sendCode(body.email());
        return Map.of("detail", "验证码已发送");
    }

    /** 注册即登录：201 带一对令牌，省一次往返。邮箱必须是刚收过码的那一个。 */
    @PostMapping("/auth/register")
    @ResponseStatus(HttpStatus.CREATED)
    public TokenPair register(@Valid @RequestBody(required = false) RegisterRequest body) {
        if (body == null) {
            throw missingBody();
        }
        return tokens(authService.register(body.username(), body.password(), body.email(), body.code()));
    }

    /** 登录：用户名（或邮箱）与口令的错给同一句「用户名或密码不正确」，不区分。 */
    @PostMapping("/auth/login")
    public TokenPair login(@Valid @RequestBody Credentials body) {
        return tokens(authService.login(body.username(), body.password()));
    }

    /** 用 refresh 令牌换新的一对；access 令牌送来这里会被拒（类型不对）。 */
    @PostMapping("/auth/refresh")
    public TokenPair refresh(@Valid @RequestBody RefreshRequest body) {
        return tokens(authService.refresh(body.refreshToken()));
    }

    /**
     * 登出：该用户此前签发的 access 与 refresh 全部作废，之后必须重新登录。
     *
     * 没有 body：凭的是已经验过的 access 令牌，服务端只记一个吊销时间点，
     * 不逐张令牌拉黑；同账号的其他设备也会一起退出。
     */
    @PostMapping("/auth/logout")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void logout(AuthenticatedUser caller) {
        authService.logout(caller.userId());
    }

    /** 当前调用方：走一次库，顺带把已注销/已删除的账号挡在这里。 */
    @GetMapping("/auth/me")
    public UserView me(AuthenticatedUser caller) {
        User user = users.get(caller.userId())
                .orElseThrow(() -> new ApiError(HttpStatus.NOT_FOUND.value(), "账号不存在"));
        return new UserView(user.id(), user.username(), user.email(), IsoTime.format(user.createdAt()));
    }

    private static ApiError missingBody() {
        FastApiValidation.Errors errors = new FastApiValidation.Errors();
        errors.add(FastApiValidation.missing(List.of("body")));
        return new ApiError(422, errors.details());
    }

    private static TokenPair tokens(Authenticated authenticated) {
        User user = authenticated.user();
        return new TokenPair(
                authenticated.accessToken(),
                authenticated.refreshToken(),
                "bearer",
                new UserView(user.id(), user.username(), user.email(), IsoTime.format(user.createdAt())));
    }
}
