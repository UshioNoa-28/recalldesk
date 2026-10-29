package com.recalldesk.domain.port.auth;

import com.recalldesk.domain.users.AuthPrincipal;
import com.recalldesk.domain.users.PrincipalType;

/**
 * 令牌的发、验与作废（实现在 infrastructure：jjwt + HS256 + Redis）。
 *
 * 端口只认「主体进、字符串出」和「字符串进、主体出或抛」。TTL、算法、密钥这些全在适配器
 * 与装配层，application 看不见 JWT 的任何形状——换非对称签名时不该动业务代码。
 */
public interface TokenGateway {

    /** 签发 access 令牌。 */
    String issueAccessToken(AuthPrincipal principal);

    /** 签发 refresh 令牌。 */
    String issueRefreshToken(AuthPrincipal principal);

    /**
     * 验签并解析主体，要求类型正好是 {@code expected}，否则抛 InvalidTokenException。
     *
     * 类型由调用方指定而不是读出来：「refresh 令牌也能当 access 用」是这类实现最常见的自伤。
     * 登出吊销也是验签的一部分，由实现顺手做掉——调用方不该各自记得去查一遍。
     */
    AuthPrincipal verify(String token, PrincipalType expected);

    /** 作废该用户此刻之前签发的全部令牌（登出：之后 verify 一律抛 InvalidTokenException）。 */
    void revoke(String userId);
}
