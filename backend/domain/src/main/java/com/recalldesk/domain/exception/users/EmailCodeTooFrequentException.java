package com.recalldesk.domain.exception.users;

/** 同一邮箱发码太频繁。 */
public class EmailCodeTooFrequentException extends RuntimeException {

    private final long retryAfterSeconds;

    public EmailCodeTooFrequentException(long retryAfterSeconds) {
        super("验证码发送过于频繁，请 " + retryAfterSeconds + " 秒后再试");
        this.retryAfterSeconds = retryAfterSeconds;
    }

    public long retryAfterSeconds() {
        return retryAfterSeconds;
    }
}
