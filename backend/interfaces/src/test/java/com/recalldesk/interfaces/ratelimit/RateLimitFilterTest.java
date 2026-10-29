package com.recalldesk.interfaces.ratelimit;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.recalldesk.domain.port.ops.RateLimiter;
import com.recalldesk.interfaces.security.AuthenticatedUser;
import com.recalldesk.interfaces.security.JwtAuthFilter;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.mock.web.MockFilterChain;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

/**
 * 限流过滤器：桶名从哪儿来、被拒时给什么。
 *
 * 与 {@link JwtAuthFilter} 一样直接驱动过滤器，不走 MockMvc——{@code @WebMvcTest} 的切片
 * 根本不带 FilterRegistrationBean，用切片测它只会得到一个绿色的空壳。
 *
 * 假 limiter 记录「桶名 + 规则名」，于是这里钉的是两件事：谁能决定自己的桶（身份，不是
 * 客户端可伪造的头），以及两类路由各用哪条规则。桶里的算法是 Redis 那侧的用例。
 */
class RateLimitFilterTest {

    /** 记请求、按脚本放行或拒绝的假限流器；name 用来区分注入的是哪一个桶。 */
    private static class FakeLimiter implements RateLimiter {

        final String name;
        final List<String> requests = new ArrayList<>();
        Decision next;

        FakeLimiter(String name, int limit) {
            this.name = name;
            this.next = Decision.allowed(limit, limit - 1);
        }

        @Override
        public Decision acquire(String bucket) {
            requests.add(name + "@" + bucket);
            return next;
        }
    }

    private final FakeLimiter perUser = new FakeLimiter("api", 30);
    private final FakeLimiter perCredential = new FakeLimiter("credential", 5);
    private final RateLimitFilter filter =
            new RateLimitFilter(perUser, perCredential, new ObjectMapper());

    private static MockHttpServletRequest request(String method, String path) {
        MockHttpServletRequest request = new MockHttpServletRequest(method, path);
        request.setRemoteAddr("203.0.113.7");
        return request;
    }

    private static MockHttpServletRequest authed(String method, String path) {
        MockHttpServletRequest request = request(method, path);
        request.setAttribute(
                JwtAuthFilter.ATTRIBUTE, new AuthenticatedUser("user-alice", "alice"));
        return request;
    }

    @Test
    @DisplayName("已认证的接口：桶名是验过的 user id，规则走 api 那条")
    void authenticatedRequestsShareTheUserBucket() throws Exception {
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(authed("GET", "/documents"), response, new MockFilterChain());

        assertThat(perUser.requests).containsExactly("api@user:user-alice");
        assertThat(response.getHeader("X-RateLimit-Limit")).isEqualTo("30");
        assertThat(response.getHeader("X-RateLimit-Remaining")).isEqualTo("29");
        assertThat(response.getStatus()).isEqualTo(HttpStatus.OK.value());
    }

    @Test
    @DisplayName("凭证路由：没有身份可用，按来源地址建桶、走更狠的那条规则")
    void credentialPathsBucketByClientAddress() throws Exception {
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(request("POST", "/auth/email-code"), response, new MockFilterChain());
        filter.doFilter(request("POST", "/auth/login"), response, new MockFilterChain());
        filter.doFilter(request("POST", "/auth/register"), response, new MockFilterChain());

        assertThat(perCredential.requests).containsOnly("credential@ip:203.0.113.7");
        assertThat(perCredential.requests).hasSize(3);
    }

    @Test
    @DisplayName("探针不计数：/health 是运维流量，不该占用户配额，也不该被别人刷到 429")
    void healthProbesAreNotCounted() throws Exception {
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(request("GET", "/health"), response, new MockFilterChain());

        assertThat(perUser.requests).isEmpty();
        assertThat(perCredential.requests).isEmpty();
        assertThat(response.getHeader("X-RateLimit-Limit")).isNull();
    }

    @Test
    @DisplayName("经 nginx 转发：桶名取 X-Real-IP，而不是 TCP 对端的前端容器地址")
    void realIpHeaderDecidesTheBucket() throws Exception {
        MockHttpServletRequest request = request("POST", "/auth/email-code");
        request.addHeader("X-Real-IP", "198.51.100.9");
        request.addHeader("X-Forwarded-For", "10.0.0.1");

        filter.doFilter(request, new MockHttpServletResponse(), new MockFilterChain());

        assertThat(perCredential.requests).containsExactly("credential@ip:198.51.100.9");
    }

    @Test
    @DisplayName("桶名不读 X-Forwarded-For：那是客户端自己写的，读它就等于自己给自己发配额")
    void forwardedHeaderIsIgnored() throws Exception {
        MockHttpServletRequest request = request("POST", "/auth/login");
        request.addHeader("X-Forwarded-For", "10.0.0.1");

        filter.doFilter(request, new MockHttpServletResponse(), new MockFilterChain());

        assertThat(perCredential.requests).containsExactly("credential@ip:203.0.113.7");
    }

    @Test
    @DisplayName("预检不计数：OPTIONS 不带凭证，把它算进某个桶是冤枉别人")
    void preflightIsNotCounted() throws Exception {
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(request("OPTIONS", "/documents"), response, new MockFilterChain());

        assertThat(perUser.requests).isEmpty();
        assertThat(perCredential.requests).isEmpty();
        assertThat(response.getHeader("X-RateLimit-Limit")).isNull();
    }

    @Test
    @DisplayName("被拒：429 + Retry-After + FastAPI 信封，下游一次都没被调用")
    void rejectionSaysWhenToComeBack() throws Exception {
        perUser.next = RateLimiter.Decision.rejected(30, 3);
        MockHttpServletResponse response = new MockHttpServletResponse();
        boolean[] reached = {false};

        filter.doFilter(
                authed("POST", "/documents"),
                response,
                (req, resp) -> reached[0] = true);

        assertThat(response.getStatus()).isEqualTo(HttpStatus.TOO_MANY_REQUESTS.value());
        assertThat(response.getHeader("Retry-After")).isEqualTo("3");
        assertThat(response.getHeader("X-RateLimit-Remaining")).isEqualTo("0");
        assertThat(response.getContentAsString()).isEqualTo("{\"detail\":\"请求过于频繁，请稍后再试\"}");
        assertThat(reached[0]).isFalse();
    }

    @Test
    @DisplayName("鉴权过滤器没发身份（不该发生）：兜进 anonymous 桶，而不是 NPE 一个 500")
    void missingIdentityFallsBackToOneBucket() throws Exception {
        filter.doFilter(request("GET", "/documents"), new MockHttpServletResponse(), new MockFilterChain());

        assertThat(perUser.requests).containsExactly("api@user:anonymous");
    }
}
