package com.recalldesk.domain.port.ops;

import java.util.function.Supplier;

/**
 * 工作单元：把应用服务编排的一段动作当作一个事务提交，正常返回即提交，抛异常即整体回滚。
 *
 * 只给应用层认识「事务边界」这个概念，不暴露具体事务 API（当前实现是 PostgreSQL 的
 * DataSource 事务，见基础设施模块）。仓储方法一律只登记、不提交，边界归调用方。
 */
public interface UnitOfWork {

    void execute(Runnable work);

    /** 同 {@link #execute(Runnable)}，带返回值。 */
    <T> T executeFor(Supplier<T> work);
}
