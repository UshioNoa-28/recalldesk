package com.recalldesk.infrastructure.security;

import com.recalldesk.domain.port.auth.PasswordHasher;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.HexFormat;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;
import org.springframework.stereotype.Component;

/**
 * PBKDF2-HMAC-SHA256 口令散列，只用 JDK，不引第三方库。
 *
 * 口令不能明文入库，也不能一次 SHA 了事——那样一个彩虹表就还原了。正确的做法是「加盐 + 反复迭代」，
 * 而 PBKDF2 正是 JDK 自带的这种算法：{@code PBKDF2WithHmacSHA256}。
 *
 * 编码串：
 * <pre>pbkdf2$&lt;迭代次数&gt;$&lt;盐的 hex&gt;$&lt;结果的 Base64&gt;</pre>
 * 迭代次数写进串里，所以以后调大成本只影响新注册的口令，旧串照样能验。
 */
@Component
public class Pbkdf2PasswordHasher implements PasswordHasher {

    private static final String ALGORITHM = "PBKDF2WithHmacSHA256";
    private static final String PREFIX = "pbkdf2";
    private static final int ITERATIONS = 210_000;
    private static final int SALT_BYTES = 16;
    private static final int HASH_BITS = 256;

    private final SecureRandom random = new SecureRandom();

    @Override
    public String hash(String plaintext) {
        byte[] salt = new byte[SALT_BYTES];
        random.nextBytes(salt);
        byte[] hash = derive(plaintext, salt, ITERATIONS);
        return PREFIX + "$" + ITERATIONS + "$" + HexFormat.of().formatHex(salt) + "$"
                + Base64.getEncoder().encodeToString(hash);
    }

    /**
     * 重算再比。串坏了（分隔符不对、不是本算法、数字解析不了）一律当作「不匹配」返回 false，
     * 而不是抛异常——库里出现坏串只可能是数据事故，不该让登录接口变成 500。
     */
    @Override
    public boolean matches(String plaintext, String encoded) {
        String[] parts = encoded == null ? new String[0] : encoded.split("\\$");
        if (parts.length != 4 || !PREFIX.equals(parts[0])) {
            return false;
        }
        try {
            int iterations = Integer.parseInt(parts[1]);
            byte[] salt = HexFormat.of().parseHex(parts[2]);
            byte[] expected = Base64.getDecoder().decode(parts[3]);
            if (iterations <= 0 || salt.length == 0) {
                return false;
            }
            // 定长比较：不在第一个不同的字节处提前返回
            return MessageDigest.isEqual(expected, derive(plaintext, salt, iterations));
        } catch (RuntimeException exc) {
            return false;
        }
    }

    private static byte[] derive(String plaintext, byte[] salt, int iterations) {
        PBEKeySpec spec = new PBEKeySpec(plaintext.toCharArray(), salt, iterations, HASH_BITS);
        try {
            return SecretKeyFactory.getInstance(ALGORITHM).generateSecret(spec).getEncoded();
        } catch (Exception exc) {
            throw new IllegalStateException("JDK 缺少 " + ALGORITHM, exc);
        } finally {
            spec.clearPassword();
        }
    }
}
