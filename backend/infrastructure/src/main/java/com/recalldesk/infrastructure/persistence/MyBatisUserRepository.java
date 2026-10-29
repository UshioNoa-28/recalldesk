package com.recalldesk.infrastructure.persistence;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.recalldesk.domain.exception.users.EmailTakenException;
import com.recalldesk.domain.exception.users.UsernameTakenException;
import com.recalldesk.domain.port.persistence.UserRepository;
import com.recalldesk.domain.users.User;
import com.recalldesk.infrastructure.persistence.mapper.UserMapper;
import com.recalldesk.infrastructure.persistence.row.UserRow;
import java.util.Optional;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Repository;

/**
 * users 表的 MyBatis-Plus 实现。
 *
 * {@code add} 把唯一索引冲突翻译成语义异常：用户名/邮箱占用是业务事实，不是数据库事故。
 * 预检（先 findByUsername / findByEmail）拦不住并发，两个请求同时通过预检时由这里的约束说话。
 * 冲突时回读一次定位是哪一列：DuplicatedKeyException 在 PostgreSQL 上带着约束名，但
 * 换驱动就会丢，回读一行的代价比猜错语义便宜。
 */
@Repository
public class MyBatisUserRepository implements UserRepository {

    private final UserMapper mapper;

    public MyBatisUserRepository(UserMapper mapper) {
        this.mapper = mapper;
    }

    @Override
    public void add(User user) {
        UserRow row = UserRow.from(user);
        try {
            mapper.insert(row);
        } catch (DuplicateKeyException exc) {
            // 两列都可能是肇事者；用户名先查，因为它是登录的主标识，报错也更具体
            if (findByUsername(user.username()).isPresent()) {
                throw new UsernameTakenException(user.username());
            }
            if (user.email() != null && findByEmail(user.email()).isPresent()) {
                throw new EmailTakenException(user.email());
            }
            throw new UsernameTakenException(user.username());
        }
    }

    @Override
    public Optional<User> findByUsername(String username) {
        return Optional.ofNullable(mapper.selectOne(new QueryWrapper<UserRow>().eq("username", username), false))
                .map(UserRow::toDomain);
    }

    @Override
    public Optional<User> findByEmail(String email) {
        return Optional.ofNullable(mapper.selectOne(new QueryWrapper<UserRow>().eq("email", email), false))
                .map(UserRow::toDomain);
    }

    @Override
    public Optional<User> get(String userId) {
        return Optional.ofNullable(mapper.selectById(userId)).map(UserRow::toDomain);
    }

}
