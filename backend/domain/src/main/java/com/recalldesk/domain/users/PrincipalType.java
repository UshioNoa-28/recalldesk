package com.recalldesk.domain.users;

/**
 * 一张令牌说的是哪种话：access 拿去认调用方，refresh 只能用来换新令牌。
 *
 * 分开是因为混用会让「拿到 access 就能续期」变成默认行为——access 泄漏时攻击者可以无限
 * 换新的，而 refresh 泄漏至少还能靠「它只在一个端点被接受」收窄。
 */
public enum PrincipalType {
    ACCESS,
    REFRESH
}
