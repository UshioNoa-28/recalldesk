package com.recalldesk.application.auth.dto;

import com.recalldesk.domain.users.User;

/**
 * 一次成功的注册/登录/刷新的结果：一对令牌 + 那个账号。
 *
 * {@code user} 里带着口令散列，出参必须由 wire DTO 重新拼一遍——直接把这对象交给
 * Jackson 就等于把散列发给调用方。
 */
public record Authenticated(String accessToken, String refreshToken, User user) {}
