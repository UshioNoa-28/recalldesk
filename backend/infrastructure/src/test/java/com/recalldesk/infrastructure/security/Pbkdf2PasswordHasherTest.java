package com.recalldesk.infrastructure.security;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class Pbkdf2PasswordHasherTest {

    private final Pbkdf2PasswordHasher hasher = new Pbkdf2PasswordHasher();

    @Test
    @DisplayName("编码串自描述：算法名、迭代次数、盐都在里面")
    void encodesParametersIntoTheHash() {
        String encoded = hasher.hash("correct horse");

        assertThat(encoded).startsWith("pbkdf2$210000$");
        assertThat(encoded.split("\\$")).hasSize(4);
    }

    @Test
    @DisplayName("同一口令两次散列不同（盐随机），但都能验过")
    void saltsPerHash() {
        String first = hasher.hash("同一个口令");
        String second = hasher.hash("同一个口令");

        assertThat(first).isNotEqualTo(second);
        assertThat(hasher.matches("同一个口令", first)).isTrue();
        assertThat(hasher.matches("同一个口令", second)).isTrue();
    }

    @Test
    @DisplayName("口令差一个字符、编码串被改坏，都只是不匹配，不抛")
    void mismatchesAreQuiet() {
        String encoded = hasher.hash("passw0rd");

        assertThat(hasher.matches("passw0rd ", encoded)).isFalse();
        assertThat(hasher.matches("", encoded)).isFalse();
        // 坏数据（字段少了、算法名不对、数字解析不了）不该让登录接口变 500
        assertThat(hasher.matches("x", "pbkdf2$210000$abcd")).isFalse();
        assertThat(hasher.matches("x", "scrypt$210000$abcd$AAAA=")).isFalse();
        assertThat(hasher.matches("x", "pbkdf2$not-a-number$abcd$AAAA=")).isFalse();
        assertThat(hasher.matches("x", "not-a-hash")).isFalse();
        assertThat(hasher.matches("x", null)).isFalse();
    }

    @Test
    @DisplayName("非空口令才有身份可言：空白串也照样能散列与比对（策略由上层管）")
    void emptyPasswordStillRoundTrips() {
        assertThat(hasher.matches("", hasher.hash(""))).isTrue();
        assertThat(hasher.matches(" ", hasher.hash(""))).isFalse();
    }
}
