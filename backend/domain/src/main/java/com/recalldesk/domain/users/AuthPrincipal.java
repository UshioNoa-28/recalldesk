package com.recalldesk.domain.users;

/**
 * 令牌里的主体：验过签名、没过期、类型对，才有这个东西。
 *
 * 只带 id 与用户名——令牌不是把用户对象随身带的容器，多塞字段（角色、配额、散列）
 * 只会让「改这些值之后旧令牌仍然生效」变成默认行为。
 */
public record AuthPrincipal(String userId, String username, PrincipalType type) {}
