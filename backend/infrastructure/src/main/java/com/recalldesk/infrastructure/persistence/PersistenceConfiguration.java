package com.recalldesk.infrastructure.persistence;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.context.annotation.Configuration;

/** Mapper 接口住在 infrastructure 这一侧，扫描也跟着模块走，不指望启动类记得扫包。 */
@Configuration(proxyBeanMethods = false)
@MapperScan("com.recalldesk.infrastructure.persistence.mapper")
public class PersistenceConfiguration {
}
