package com.recalldesk.interfaces.security;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.recalldesk.domain.port.auth.TokenGateway;
import com.recalldesk.domain.users.AuthPrincipal;
import com.recalldesk.domain.exception.users.InvalidTokenException;
import com.recalldesk.domain.users.PrincipalType;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockFilterChain;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

/**
 * 鉴权过滤器的行为：哪些路径不要凭证、凭证不对时给什么、验过了把身份放在哪儿。
 *
 * 过滤器在 MVC 之外，advice 管不到它，所以错误信封得自己写——这正是单测替我不了的部分：
 * 断言的不是「抛了 InvalidTokenException」，而是调用方实际看到的 401 + {@code {"detail": ...}}。
 */
class JwtAuthFilterTest {

    private static final List<String> PUBLIC = List.of("/auth/register", "/auth/login", "/auth/refresh", "/health");

    private final FakeGateway gateway = new FakeGateway();
    private final JwtAuthFilter filter = new JwtAuthFilter(gateway, PUBLIC, new ObjectMapper());

    @Test
    @DisplayName("白名单路径不读令牌：带着坏凭证也照样过去（公开路由自己决定给什么）")
    void publicPathsSkipVerification() throws Exception {
        MockFilterChain chain = new MockFilterChain();

        Outcome outcome = run("POST", "/auth/login", "Bearer 随便什么", chain);

        assertThat(outcome.response().getStatus()).isEqualTo(200);
        assertThat(gateway.verified).isEmpty();
        assertThat(chain.getRequest()).isNotNull(); // 请求被交给了下游
    }

    @Test
    @DisplayName("白名单是前缀匹配：/health 与 /health/live 都算公开，/healthz 不算")
    void publicPrefixMatching() throws Exception {
        assertThat(run("GET", "/health/live", null).response().getStatus()).isEqualTo(200);
        assertThat(run("GET", "/health", null).response().getStatus()).isEqualTo(200);
        assertThat(run("GET", "/healthz", null).response().getStatus()).isEqualTo(401);
    }

    @Test
    @DisplayName("缺 Authorization：401 缺少访问令牌，且不往链上走")
    void missingHeaderIsRejected() throws Exception {
        MockFilterChain chain = new MockFilterChain();

        Outcome outcome = run("GET", "/documents", null, chain);

        assertThat(outcome.response().getStatus()).isEqualTo(401);
        assertThat(outcome.response().getContentAsString()).isEqualTo("{\"detail\":\"缺少访问令牌\"}");
        assertThat(chain.getRequest()).isNull();
    }

    @Test
    @DisplayName("不是 Bearer 前缀（Basic / 裸令牌 / 小写 bearer）：一律当没登录")
    void nonBearerSchemeIsRejected() throws Exception {
        for (String header : List.of("Basic dXNlcjpwYXNz", "eyJhbGci", "bearer abc")) {
            assertThat(run("GET", "/documents", header).response().getStatus())
                    .as("header=%s", header)
                    .isEqualTo(401);
        }
        assertThat(gateway.verified).isEmpty();
    }

    @Test
    @DisplayName("令牌类型必须是 ACCESS，且送去验的是 trim 过的那串")
    void verifiesAsAccessTokenAndPassesTheType() throws Exception {
        run("GET", "/documents", "Bearer  access-token ");

        assertThat(gateway.verified).containsExactly("access-token");
        assertThat(gateway.expected).containsExactly(PrincipalType.ACCESS);
    }

    @Test
    @DisplayName("验过了才有身份：AuthenticatedUser 落在 request attribute 里，只有 id 与用户名")
    void putsPrincipalOnTheRequest() throws Exception {
        Outcome outcome = run("GET", "/documents", "Bearer ok");

        assertThat(outcome.request().getAttribute(JwtAuthFilter.ATTRIBUTE))
                .isEqualTo(new AuthenticatedUser("user-1", "alice"));
    }

    @Test
    @DisplayName("令牌过期/签名不对：401 登录状态已失效，身份绝不落进 request")
    void invalidTokenBecomesDetailEnvelope() throws Exception {
        gateway.reject = true;
        MockFilterChain chain = new MockFilterChain();

        Outcome outcome = run("GET", "/documents", "Bearer 旧令牌", chain);

        assertThat(outcome.response().getStatus()).isEqualTo(401);
        assertThat(outcome.response().getContentType()).isEqualTo("application/json");
        assertThat(outcome.response().getContentAsString()).isEqualTo("{\"detail\":\"登录状态已失效，请重新登录\"}");
        assertThat(outcome.request().getAttribute(JwtAuthFilter.ATTRIBUTE)).isNull();
        assertThat(chain.getRequest()).isNull();
    }

    @Test
    @DisplayName("预检不带凭证：OPTIONS 直接放行，否则浏览器跨域永远到不了路由")
    void optionsPreflightPassesThrough() throws Exception {
        MockFilterChain chain = new MockFilterChain();

        assertThat(run("OPTIONS", "/documents", null, chain).response().getStatus()).isEqualTo(200);
        assertThat(chain.getRequest()).isNotNull();
        assertThat(gateway.verified).isEmpty();
    }

    private Outcome run(String method, String path, String authorization) throws Exception {
        return run(method, path, authorization, new MockFilterChain());
    }

    /** 一次请求的现场：响应给调用方看，request 与 chain 给断言查「身份落到哪儿、走没走到下游」。 */
    private Outcome run(String method, String path, String authorization, MockFilterChain chain) throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest(method, path);
        if (authorization != null) {
            request.addHeader("Authorization", authorization);
        }
        MockHttpServletResponse response = new MockHttpServletResponse();
        filter.doFilter(request, response, chain);
        return new Outcome(request, response);
    }

    private record Outcome(MockHttpServletRequest request, MockHttpServletResponse response) {}

    /** 假网关：记下送来的令牌与要求的类型，按开关决定放行还是抛。 */
    private static class FakeGateway implements TokenGateway {

        final List<String> verified = new ArrayList<>();
        final List<PrincipalType> expected = new ArrayList<>();
        boolean reject;

        @Override
        public String issueAccessToken(AuthPrincipal principal) {
            throw new UnsupportedOperationException();
        }

        @Override
        public String issueRefreshToken(AuthPrincipal principal) {
            throw new UnsupportedOperationException();
        }

        @Override
        public AuthPrincipal verify(String token, PrincipalType type) {
            verified.add(token);
            expected.add(type);
            if (reject) {
                throw new InvalidTokenException("expired");
            }
            return new AuthPrincipal("user-1", "alice", type);
        }

        @Override
        public void revoke(String userId) {
            throw new UnsupportedOperationException();
        }
    }
}
