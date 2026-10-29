package com.recalldesk.interfaces.security;

import com.recalldesk.interfaces.web.ApiError;
import org.springframework.core.MethodParameter;
import org.springframework.stereotype.Component;
import org.springframework.web.bind.support.WebDataBinderFactory;
import org.springframework.web.context.request.NativeWebRequest;
import org.springframework.web.context.request.RequestAttributes;
import org.springframework.web.method.support.HandlerMethodArgumentResolver;
import org.springframework.web.method.support.ModelAndViewContainer;

/**
 * 把 {@link JwtAuthFilter} 验过的身份变成控制器参数：签名里写 {@link AuthenticatedUser} 就是「此路由要登录」。
 *
 * 属性缺失意味着过滤器没给过身份——白名单路径不该声明这个参数，声明了就当编程错误处理。
 * 给 401 而不是 500：调用方看到的仍是「你没登录」，不是内部结构泄漏。
 *
 * 是个 {@code @Component} 而不是 {@code AuthConfiguration} 里 new 出来的 bean：{@code @WebMvcTest}
 * 会自动收下 {@code HandlerMethodArgumentResolver}，路由切片测试因此不用另配一套解析器。
 */
@Component
public class AuthenticatedUserArgumentResolver implements HandlerMethodArgumentResolver {

    @Override
    public boolean supportsParameter(MethodParameter parameter) {
        return AuthenticatedUser.class.equals(parameter.getParameterType());
    }

    @Override
    public Object resolveArgument(
            MethodParameter parameter,
            ModelAndViewContainer mavContainer,
            NativeWebRequest webRequest,
            WebDataBinderFactory binderFactory) {
        Object principal = webRequest.getAttribute(JwtAuthFilter.ATTRIBUTE, RequestAttributes.SCOPE_REQUEST);
        if (principal == null) {
            throw new ApiError(401, "缺少访问令牌");
        }
        return principal;
    }
}
