package com.recalldesk.domain.users;

import java.time.Instant;

/**
 * 一个账号。
 *
 * {@code passwordHash} 是 PBKDF2 的自描述编码串（含迭代次数与盐），不是明文也不是可逆东西；
 * 它留在这里是因为登录校验必须读它——但它**永不进响应体**，出参一律走专门的 wire DTO。
 * username 入库前已转小写，所以唯一性是大小写不敏感的，不必在 SQL 里做 lower()。
 *
 * {@code email} 是注册时经验证码确认过的地址（归一为小写），同样全局唯一；它也是登录时可用的
 * 第二标识。允许为空是为了兼容「加邮箱之前就存在的账号」——它们仍然只能用用户名登录。
 */
public record User(String id, String username, String passwordHash, String email, Instant createdAt) {}
