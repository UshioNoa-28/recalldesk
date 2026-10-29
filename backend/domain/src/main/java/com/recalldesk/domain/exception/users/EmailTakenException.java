package com.recalldesk.domain.exception.users;

/** 邮箱已被占用。 */
public class EmailTakenException extends RuntimeException {

    public EmailTakenException(String email) {
        super("该邮箱已被注册: " + email);
    }
}
