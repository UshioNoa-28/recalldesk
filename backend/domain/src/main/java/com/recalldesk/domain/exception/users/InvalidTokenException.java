package com.recalldesk.domain.exception.users;

/** 令牌无效：签名不符、过期或类型不对。 */
public class InvalidTokenException extends RuntimeException {

    public InvalidTokenException(String reason) {
        super("凭证无效: " + reason);
    }
}
