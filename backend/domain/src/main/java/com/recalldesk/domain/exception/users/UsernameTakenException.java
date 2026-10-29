package com.recalldesk.domain.exception.users;

/** 用户名已被占用。 */
public class UsernameTakenException extends RuntimeException {

    public UsernameTakenException(String username) {
        super("用户名 " + username + " 已被占用");
    }
}
