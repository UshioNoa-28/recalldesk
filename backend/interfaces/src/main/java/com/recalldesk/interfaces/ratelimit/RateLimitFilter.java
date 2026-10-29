package com.recalldesk.interfaces.ratelimit;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.recalldesk.domain.port.ops.RateLimiter;
import com.recalldesk.interfaces.security.AuthenticatedUser;
import com.recalldesk.interfaces.security.JwtAuthFilter;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.Map;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * 限流：普通接口按用户一个桶，发码/注册/登录/刷新按客户端 IP 一个桶。
 *
 * 两套桶是两个实现，各自带着自己的限额（见 infrastructure.ratelimit）：凭证那段还没有身份，
 * 只能按来源地址限；而且凭证接口失败一次就能判断口令对不对，限额要严得多。
 *
 * 排在 {@link JwtAuthFilter} 之后：那时 request 上已经挂着验过的身份，桶名才可信。
 * 来源地址优先取 nginx 覆盖写入的 {@code X-Real-IP}，没有才回落 {@code getRemoteAddr()}；
 * {@code X-Forwarded-For} 不读——它是追加语义，左侧客户端可写，换一个值就能换一个桶。
 */
public class RateLimitFilter extends OncePerRequestFilter {

    /** 429 的一句话文案：还剩几个在响应头里，正文不再重复。 */
    static final String TOO_MANY = "请求过于频繁，请稍后再试";

    private final RateLimiter perUser;
    private final RateLimiter perCredential;
    private final ObjectMapper objectMapper;

    public RateLimitFilter(RateLimiter perUser, RateLimiter perCredential, ObjectMapper objectMapper) {
        this.perUser = perUser;
        this.perCredential = perCredential;
        this.objectMapper = objectMapper;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String path = request.getRequestURI();
        // 预检不带凭证；/health 是探针流量。两者都不该占用户配额，也不该因为别人刷接口而吃 429
        if ("OPTIONS".equalsIgnoreCase(request.getMethod()) || path.equals("/health")) {
            chain.doFilter(request, response);
            return;
        }
        boolean credential = isCredentialPath(path);
        String bucket = credential
                ? "ip:" + clientAddress(request)
                : "user:" + identityOrDefault(request);
        RateLimiter.Decision decision = (credential ? perCredential : perUser).acquire(bucket);
        response.setHeader("X-RateLimit-Limit", String.valueOf(decision.limit()));
        response.setHeader("X-RateLimit-Remaining", String.valueOf(decision.remaining()));
        if (!decision.allowed()) {
            reject(response, decision.retryAfterSeconds());
            return;
        }
        chain.doFilter(request, response);
    }

    /**
     * 公开且吃凭证的那几条：发码/注册/登录/刷新 按 ip来限流
     */
    private static boolean isCredentialPath(String path) {
        return path.equals("/auth/email-code")
                || path.equals("/auth/login")
                || path.equals("/auth/register")
                || path.equals("/auth/refresh");
    }

    /**
     * 真实来源地址：经 nginx 转发时 TCP 对端永远是前端容器，浏览器地址只在 nginx 覆盖写入的
     * X-Real-IP 里。直连（开发时 Vite 代理、本机调试）没有这个头，回落 getRemoteAddr()。
     */
    private static String clientAddress(HttpServletRequest request) {
        String realIp = request.getHeader("X-Real-IP");
        return realIp == null || realIp.isBlank() ? request.getRemoteAddr() : realIp.strip();
    }

    /**
     * 拿不到的身份兜成 "anonymous"：公开路径要么上面跳过（/health、预检），要么是凭证四条走
     * IP 桶；受保护路径由鉴权过滤器保证带身份。兜底只防配置漂移（白名单多了一条），
     * 比 NPE 一个 500 好。
     */
    private static String identityOrDefault(HttpServletRequest request) {
        Object caller = request.getAttribute(JwtAuthFilter.ATTRIBUTE);
        return caller instanceof AuthenticatedUser user ? user.userId() : "anonymous";
    }

    private void reject(HttpServletResponse response, long retryAfterSeconds) throws IOException {
        response.setStatus(HttpStatus.TOO_MANY_REQUESTS.value());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setHeader(HttpHeaders.RETRY_AFTER, String.valueOf(retryAfterSeconds));
        response.getWriter().write(objectMapper.writeValueAsString(Map.of("detail", TOO_MANY)));
    }
}
