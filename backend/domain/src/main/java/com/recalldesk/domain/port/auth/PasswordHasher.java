package com.recalldesk.domain.port.auth;

/**
 * 口令散列（实现在 infrastructure：JDK 自带的 PBKDF2WithHmacSHA256）。
 *
 * 编码串自描述（算法、迭代次数、盐都在里面），所以以后调参数不必迁移数据：
 * 旧串照样能验，新注册用新参数。{@code matches} 必须在长度未知的比较上不提前返回。
 */
public interface PasswordHasher {

    String hash(String plaintext);

    /** 用编码串里自带的参数重算并比对；串本身不是合法编码时返回 false（而不是抛）。 */
    boolean matches(String plaintext, String encoded);
}
