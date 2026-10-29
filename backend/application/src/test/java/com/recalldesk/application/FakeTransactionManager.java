package com.recalldesk.application;

import com.recalldesk.domain.port.ops.UnitOfWork;
import java.util.function.Supplier;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.TransactionException;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.support.SimpleTransactionStatus;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * 假事务：只数提交次数与回滚次数，供事务边界用例断言。
 *
 * 工作单元用真的 TransactionTemplate 包它，所以「写失败要回滚」「提交失败照样抛」
 * 这些模板行为也是被测的——换成手写 lambda 假件就等于把事务边界这块最要紧的逻辑跳过了。
 */
public class FakeTransactionManager implements PlatformTransactionManager {

    private final TransactionTemplate template = new TransactionTemplate(this);

    public int commits;
    public int rollbacks;
    public RuntimeException failOnCommit;

    @Override
    public TransactionStatus getTransaction(TransactionDefinition definition) throws TransactionException {
        return new SimpleTransactionStatus();
    }

    @Override
    public void commit(TransactionStatus status) {
        if (failOnCommit != null) {
            throw failOnCommit;
        }
        commits++;
    }

    @Override
    public void rollback(TransactionStatus status) {
        rollbacks++;
    }

    /** 套在模板里用：service 依赖的是 UnitOfWork，不是管理器本身。 */
    public UnitOfWork unitOfWork() {
        return new UnitOfWork() {
            @Override
            public void execute(Runnable work) {
                template.executeWithoutResult(status -> work.run());
            }

            @Override
            public <T> T executeFor(Supplier<T> work) {
                return template.execute(status -> work.get());
            }
        };
    }
}
