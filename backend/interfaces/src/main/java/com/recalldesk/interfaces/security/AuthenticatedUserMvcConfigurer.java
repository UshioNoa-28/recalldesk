package com.recalldesk.interfaces.security;

import java.util.List;
import org.springframework.stereotype.Component;
import org.springframework.web.method.support.HandlerMethodArgumentResolver;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * 把 {@link AuthenticatedUserArgumentResolver} 挂进 MVC 的参数解析器列表。
 *
 * 单独一个类而不是塞在 {@code AuthConfiguration} 的 {@code @Bean} 方法里：{@code @WebMvcTest}
 * 按类型筛切片组件（{@code WebMvcConfigurer} 在名单里），拆开后路由切片测试不用为了拿一个
 * 解析器去加载整套 JWT 配置（密钥、TTL、白名单）。
 *
 * 这里只加解析器：没有 Spring Security 的过滤链，也就没有它的注解与表达式。
 */
@Component
public class AuthenticatedUserMvcConfigurer implements WebMvcConfigurer {

    private final AuthenticatedUserArgumentResolver resolver;

    public AuthenticatedUserMvcConfigurer(AuthenticatedUserArgumentResolver resolver) {
        this.resolver = resolver;
    }

    @Override
    public void addArgumentResolvers(List<HandlerMethodArgumentResolver> resolvers) {
        resolvers.add(resolver);
    }
}
