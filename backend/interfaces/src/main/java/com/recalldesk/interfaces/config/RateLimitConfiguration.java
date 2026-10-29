package com.recalldesk.interfaces.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.recalldesk.domain.port.ops.RateLimiter;
import com.recalldesk.interfaces.ratelimit.RateLimitFilter;
import java.util.List;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.Ordered;

/**
 * 限流接线：两个桶按类型注入，过滤器排在鉴权之后。
 *
 * 限额写在两个实现自己身上（PerUserRateLimiter / PerCredentialRateLimiter）；
 * 换一种限流算法就是换那两个 {@link RateLimiter} 的实现，这里不用动。
 *
 * 关掉限流用 {@code RECALLDESK_RATE_LIMIT_ENABLED=false}，且关掉是「不注册过滤器」
 * 而不是「注册一个每次都放行的过滤器」——后者会让一个已经决定不限的部署仍然每请求打一次 Redis。
 */
@Configuration(proxyBeanMethods = false)
public class RateLimitConfiguration {

    @Bean
    @ConditionalOnProperty(name = "recalldesk.rate-limit.enabled", havingValue = "true", matchIfMissing = true)
    public FilterRegistrationBean<RateLimitFilter> rateLimitFilter(
            @Qualifier("perUserRateLimiter") RateLimiter perUser,
            @Qualifier("perCredentialRateLimiter") RateLimiter perCredential,
            ObjectMapper objectMapper) {
        FilterRegistrationBean<RateLimitFilter> registration =
                new FilterRegistrationBean<>(new RateLimitFilter(perUser, perCredential, objectMapper));
        registration.setUrlPatterns(List.of("/*"));
        // 鉴权(+10) → 限流(+20)：桶名要用验过的身份，所以必须排在鉴权之后
        registration.setOrder(Ordered.HIGHEST_PRECEDENCE + 20);
        return registration;
    }
}
