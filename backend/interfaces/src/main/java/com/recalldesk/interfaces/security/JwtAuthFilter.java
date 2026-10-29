package com.recalldesk.interfaces.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.recalldesk.domain.exception.users.InvalidTokenException;
import com.recalldesk.domain.port.auth.TokenGateway;
import com.recalldesk.domain.users.AuthPrincipal;
import com.recalldesk.domain.users.PrincipalType;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * 唯一的鉴权入口：一个 Bearer 令牌换一次身份，换不到就 401，绝不放行到控制器。
 *
 * 登出吊销不需要在这里写第二遍：令牌验签本身就会拒掉「登出之前签发」的那批。
 *
 * 不引 Spring Security 整套过滤链，是因为这个项目需要的只有「验一张自发的 JWT + 一条公开
 * 路径白名单」，而 Security 的默认形态会把这两件事包装成十几个可扩展点。代价是这里要自己
 * 把错误体写成 {@code {"detail": ...}}——过滤器在 MVC 之外，advice 管不到它。
 *
 * 验过的身份放进 request attribute，由 {@link AuthenticatedUserArgumentResolver}
 * 变成控制器参数；下游没有第二个「读令牌」的地方，也就没有读到旧令牌的路径。
 */
public class JwtAuthFilter extends OncePerRequestFilter {

    /** 验过的 {@link AuthenticatedUser} 存放处。 */
    public static final String ATTRIBUTE = "recalldesk.authenticated";

    private static final String BEARER_PREFIX = "Bearer ";

    private final TokenGateway tokens;
    private final List<String> publicPaths;
    private final ObjectMapper objectMapper;

    public JwtAuthFilter(TokenGateway tokens, List<String> publicPaths, ObjectMapper objectMapper) {
        this.tokens = tokens;
        this.publicPaths = List.copyOf(publicPaths);
        this.objectMapper = objectMapper;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String path = request.getRequestURI();
        // 预检不带也不该带凭证；公开路径由各自的路由自己决定给什么
        if ("OPTIONS".equalsIgnoreCase(request.getMethod()) || isPublic(path)) {
            chain.doFilter(request, response);
            return;
        }
        String header = request.getHeader("Authorization");
        if (header == null || !header.startsWith(BEARER_PREFIX)) {
            reject(response, "缺少访问令牌");
            return;
        }
        try {
            AuthPrincipal principal =
                    tokens.verify(header.substring(BEARER_PREFIX.length()).trim(), PrincipalType.ACCESS);
            request.setAttribute(ATTRIBUTE, new AuthenticatedUser(principal.userId(), principal.username()));
        } catch (InvalidTokenException exc) {
            reject(response, "登录状态已失效，请重新登录");
            return;
        }
        chain.doFilter(request, response);
    }

    /** 精确或带斜杠的前缀匹配：/auth/login、/health 这类，其余一律要凭证。 */
    private boolean isPublic(String path) {
        return publicPaths.stream().anyMatch(prefix -> path.equals(prefix) || path.startsWith(prefix + "/"));
    }

    private void reject(HttpServletResponse response, String detail) throws IOException {
        response.setStatus(HttpStatus.UNAUTHORIZED.value());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        // detail 用 Map 而不是 record：过滤器里没有 MVC 的信封装配，手写就照 FastAPI 的两键结构
        response.getWriter().write(objectMapper.writeValueAsString(Map.of("detail", detail)));
    }
}
