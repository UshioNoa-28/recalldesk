package com.recalldesk.domain.port.persistence;

import com.recalldesk.domain.users.User;
import java.util.Optional;

/** users 表的访问能力。没有 update：用户名不可改、口令改的是散列列，走 changePassword 再说。 */
public interface UserRepository {

    void add(User user);

    /** 按用户名查（入参必须已归一：{@code UserIdentity.of}）。 */
    Optional<User> findByUsername(String username);

    /**
     * 按邮箱查（入参必须已归一）：注册查重与「用邮箱登录」都靠它。
     *
     * 早于邮箱上线的账号 email 为空，索引上不冲突（PostgreSQL 的唯一约束不拦 NULL）。
     */
    Optional<User> findByEmail(String email);

    Optional<User> get(String userId);
}
