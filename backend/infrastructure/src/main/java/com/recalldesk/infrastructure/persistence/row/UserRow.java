package com.recalldesk.infrastructure.persistence.row;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.recalldesk.domain.users.User;
import java.time.Instant;
import lombok.Data;

/** users 表的一行。created_at 交给库的 DEFAULT now()，插入时留 null 即可。 */
@Data
@TableName("users")
public class UserRow {

    @TableId(type = IdType.INPUT)
    private String id;

    private String username;
    private String passwordHash;
    /** 注册时经验证码确认过的地址；邮箱上线之前的老账号为 null（唯一约束不拦 NULL）。 */
    private String email;
    private Instant createdAt;

    /** 领域对象 → 行。 */
    public static UserRow from(User user) {
        UserRow row = new UserRow();
        row.setId(user.id());
        row.setUsername(user.username());
        row.setPasswordHash(user.passwordHash());
        row.setEmail(user.email());
        row.setCreatedAt(user.createdAt());
        return row;
    }

    public User toDomain() {
        return new User(id, username, passwordHash, email, createdAt);
    }
}
