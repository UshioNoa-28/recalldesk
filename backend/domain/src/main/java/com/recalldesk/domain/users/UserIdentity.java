package com.recalldesk.domain.users;

import java.util.Locale;

/**
 * 用户标识的归一值：用户名与邮箱共用同一条规则——去首尾空白、转小写。
 *
 * 放在 domain 是因为「什么算同一个用户名／邮箱」是业务事实（大小写不敏感），
 * 唯一索引与登录查询都依赖它，而不是某个入口的输入便利。
 */
public record UserIdentity(String value) {

    public static UserIdentity of(String raw) {
        return new UserIdentity(raw == null ? "" : raw.strip().toLowerCase(Locale.ROOT));
    }
}
