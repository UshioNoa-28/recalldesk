package com.recalldesk.interfaces.security;

/**
 * 控制器拿到的当前调用方（由 {@link AuthenticatedUserArgumentResolver} 从请求属性里取）。
 *
 * 只有 id 与用户名：作用域、配额、角色都不在这里，它们属于查询条件而不是身份——
 * 塞进身份对象就会有人开始信「令牌里写了就能改」。
 */
public record AuthenticatedUser(String userId, String username) {}
