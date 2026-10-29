package com.recalldesk.infrastructure.transaction;

import com.recalldesk.domain.port.ops.UnitOfWork;
import java.util.function.Supplier;
import org.springframework.stereotype.Component;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * 工作单元的事务实现：每个 execute 就是一个本地事务（加入外层事务，若有）。
 *
 * 管理器由 Spring Boot 按数据源自动配置（DataSourceTransactionManager），
 * 这里只把它包成应用层认识的端口，组合根不再导出事务模板。
 */
@Component
public class SpringUnitOfWork implements UnitOfWork {

    private final TransactionTemplate template;

    public SpringUnitOfWork(PlatformTransactionManager transactionManager) {
        this.template = new TransactionTemplate(transactionManager);
    }

    @Override
    public void execute(Runnable work) {
        template.executeWithoutResult(status -> work.run());
    }

    @Override
    public <T> T executeFor(Supplier<T> work) {
        return template.execute(status -> work.get());
    }
}
