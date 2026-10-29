package com.recalldesk.domain.exception.users;

/** 用户名或口令不对；两种情况刻意不区分。 */
public class BadCredentialsException extends RuntimeException {

    public BadCredentialsException() {
        super("用户名或密码不正确");
    }
}
