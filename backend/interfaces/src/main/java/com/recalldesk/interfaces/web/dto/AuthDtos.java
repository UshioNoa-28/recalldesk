package com.recalldesk.interfaces.web.dto;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

/**
 * 账号路由的出入参形状。
 *
 * 形状校验（非空、长度、邮箱格式）打在字段注解上，进入 controller 前由 Bean Validation 拦下；
 * 业务规则（查重、验证码、散列比对）仍归 AuthService。
 *
 * 出参必须重新拼一遍而不得直接序列化 {@code User}：领域里的 User 带着口令散列，
 * 少包一层就等于把散列发给调用方。
 */
public final class AuthDtos {

    private AuthDtos() {}

    /**
     * POST /auth/login 的入参。
     *
     * username 一栏可以填用户名也可以填邮箱——它是"标识"而不是"用户名"，
     * 改字段名会破坏已有客户端，所以名字留着、语义在服务层按有没有 @ 判。
     */
    public record Credentials(
            @NotBlank(message = "用户名不能为空") String username,
            @NotBlank(message = "密码不能为空") String password) {}

    /** POST /auth/register 的入参：比登录多一个已验证过的邮箱与它的验证码。 */
    public record RegisterRequest(
            @NotBlank(message = "用户名不能为空") String username,
            @NotBlank(message = "密码不能为空")
                    @Size(min = 8, max = 32, message = "密码需为 8-32 位") String password,
            @NotBlank(message = "邮箱不能为空") @Email(message = "邮箱格式不正确") String email,
            @NotBlank(message = "验证码不能为空") String code) {}

    /** POST /auth/email-code 的入参。 */
    public record EmailCodeRequest(
            @NotBlank(message = "邮箱不能为空") @Email(message = "邮箱格式不正确") String email) {}

    /** POST /auth/refresh 的入参（全局 snake_case 命名策略下即 refresh_token）。 */
    public record RefreshRequest(
            @NotBlank(message = "refresh_token 不能为空") String refreshToken) {}

    /** 三个发牌端点共用：一次成功的注册即等于登录，省掉「注册完再登一次」的往返。 */
    public record TokenPair(
            String accessToken, String refreshToken, String tokenType, UserView user) {}

    /** GET /auth/me 与 TokenPair 里的那份身份，字段与令牌里的完全一致（email 可能为空）。 */
    public record UserView(String id, String username, String email, String createdAt) {}
}
