package com.recalldesk.domain.exception.users;

/** 验证码不对、已过期或已被用过；三种情况刻意不区分。 */
public class EmailCodeInvalidException extends RuntimeException {

    public EmailCodeInvalidException() {
        super("验证码不正确或已过期");
    }
}
