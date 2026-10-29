package com.recalldesk.interfaces.web;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.verify;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.BDDMockito.given;
import static org.mockito.BDDMockito.willThrow;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.recalldesk.application.auth.AuthService;
import com.recalldesk.application.auth.dto.Authenticated;
import com.recalldesk.application.auth.EmailCodeService;
import com.recalldesk.domain.port.persistence.UserRepository;
import com.recalldesk.domain.exception.users.BadCredentialsException;
import com.recalldesk.domain.exception.users.EmailCodeInvalidException;
import com.recalldesk.domain.exception.users.EmailCodeTooFrequentException;
import com.recalldesk.domain.exception.users.EmailTakenException;
import com.recalldesk.domain.exception.users.InvalidTokenException;
import com.recalldesk.domain.users.User;
import com.recalldesk.domain.exception.users.UsernameTakenException;
import com.recalldesk.interfaces.security.AuthenticatedUser;
import com.recalldesk.interfaces.security.JwtAuthFilter;
import java.time.Instant;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;

/**
 * 账号路由的 HTTP 契约测试。
 *
 * 这一层只负责形状与状态码，口令策略与令牌签发都在 {@link AuthService}（它有自己的用例）。
 * 这里要钉住的是两件出事就得上安全事件清单的事：出参里不许出现口令散列，以及
 * 「谁都能拿到别人的令牌」——后者靠 {@code /auth/me} 的身份只来自令牌、不来自请求参数。
 */
@WebMvcTest(controllers = AuthController.class)
class AuthControllerTest {

    private static final String HASH = "pbkdf2$210000$c2FsdA$digest";
    private static final Instant CREATED = Instant.parse("2026-09-03T12:00:00Z");
    private static final User ALICE = new User("user-1", "alice", HASH, "alice@example.com", CREATED);

    @Autowired
    private MockMvc mvc;

    @MockitoBean
    private AuthService authService;

    @MockitoBean
    private EmailCodeService emailCodeService;

    @MockitoBean
    private UserRepository users;

    private static Authenticated pair() {
        return new Authenticated("access-abc", "refresh-xyz", ALICE);
    }

    @Test
    @DisplayName("POST /auth/register：201 带一对令牌，出参只有 snake_case 的四键与身份三键")
    void registerReturnsTokenPair() throws Exception {
        given(authService.register("alice", "pw123456", "alice@example.com", "123456")).willReturn(pair());

        String body = mvc.perform(post("/auth/register").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"alice\",\"password\":\"pw123456\","
                                + "\"email\":\"alice@example.com\",\"code\":\"123456\"}"))
                .andExpect(status().isCreated())
                .andExpect(content().json("""
                        {"access_token":"access-abc","refresh_token":"refresh-xyz","token_type":"bearer",
                         "user":{"id":"user-1","username":"alice","email":"alice@example.com",
                                 "created_at":"2026-09-03T12:00:00+00:00"}}""", true))
                .andReturn().getResponse().getContentAsString();

        // 领域对象带着口令散列，出参必须重拼一遍：散列漏出去就是离线爆破的原料
        assertThat(body).doesNotContain("pbkdf2").doesNotContain("password_hash").doesNotContain("passwordHash");
    }

    @Test
    @DisplayName("POST /auth/email-code：202 只回一条已受理；邮箱交给服务层去归一/发信")
    void emailCodeAccepted() throws Exception {
        mvc.perform(post("/auth/email-code").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"email\":\"Alice@Example.com\"}"))
                .andExpect(status().isAccepted())
                .andExpect(content().json("{\"detail\":\"验证码已发送\"}", true));

        // 归一（小写、去空白）在服务层做：控制器原样转发，不自己判字符串
        verify(emailCodeService).sendCode("Alice@Example.com");
    }

    @Test
    @DisplayName("POST /auth/email-code：太频繁 429 带 Retry-After；没有 body 422")
    void emailCodeTooFrequent() throws Exception {
        willThrow(new EmailCodeTooFrequentException(42)).given(emailCodeService).sendCode(anyString());

        mvc.perform(post("/auth/email-code").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"email\":\"alice@example.com\"}"))
                .andExpect(status().isTooManyRequests())
                .andExpect(jsonPath("$..detail").exists());

        mvc.perform(post("/auth/email-code"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.detail[0].type").value("missing"));
    }

    @Test
    @DisplayName("DTO 注解：口令过短/邮箱不合法在进 service 前就 422")
    void validationAnnotations() throws Exception {
        String body = mvc.perform(post("/auth/register").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"alice\",\"password\":\"short\","
                                + "\"email\":\"not-an-email\",\"code\":\"123456\"}"))
                .andExpect(status().isUnprocessableEntity())
                .andReturn().getResponse().getContentAsString();

        assertThat(body).contains("密码需为 8-32 位").contains("邮箱格式不正确");
        verifyNoInteractions(authService, emailCodeService);
    }

    @Test
    @DisplayName("POST /auth/register：邮箱被占 400、验证码不对 400，文案分得清")
    void registerEmailFailures() throws Exception {
        // given(...).willThrow 会把参数当「返回值」，异常在打桩阶段就抛了；错误路径统一用 willThrow(...)
        willThrow(new EmailTakenException("alice@example.com"))
                .given(authService).register(anyString(), anyString(), anyString(), anyString());
        mvc.perform(post("/auth/register").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"alice\",\"password\":\"pw123456\","
                                + "\"email\":\"alice@example.com\",\"code\":\"123456\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(content().json("{\"detail\":\"该邮箱已被注册\"}", true));

        willThrow(new EmailCodeInvalidException())
                .given(authService).register(anyString(), anyString(), anyString(), anyString());
        mvc.perform(post("/auth/register").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"bob\",\"password\":\"pw123456\","
                                + "\"email\":\"bob@example.com\",\"code\":\"000000\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(content().json("{\"detail\":\"验证码不正确或已过期\"}", true));
    }

    @Test
    @DisplayName("POST /auth/login：200；用户名不存在与口令错是同一句 401（挡用户名枚举）")
    void loginAndBadCredentials() throws Exception {
        given(authService.login("alice", "pw123456")).willReturn(pair());

        mvc.perform(post("/auth/login").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"alice\",\"password\":\"pw123456\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.access_token").value("access-abc"));

        willThrow(new BadCredentialsException()).given(authService).login(anyString(), anyString());
        mvc.perform(post("/auth/login").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"nobody\",\"password\":\"whatever\"}"))
                .andExpect(status().isUnauthorized())
                .andExpect(content().json("{\"detail\":\"用户名或密码不正确\"}", true));
    }

    @Test
    @DisplayName("POST /auth/refresh：refresh 换新的一对；access 拿来刷新是 401")
    void refreshSwapsThePair() throws Exception {
        given(authService.refresh("refresh-xyz")).willReturn(pair());

        mvc.perform(post("/auth/refresh").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"refresh_token\":\"refresh-xyz\"}"))
                .andExpect(status().isOk())
                .andExpect(content().json("""
                        {"access_token":"access-abc","refresh_token":"refresh-xyz","token_type":"bearer",
                         "user":{"id":"user-1","username":"alice","email":"alice@example.com",
                                 "created_at":"2026-09-03T12:00:00+00:00"}}""", true));

        given(authService.refresh("access-abc")).willThrow(new InvalidTokenException("type=access"));
        mvc.perform(post("/auth/refresh").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"refresh_token\":\"access-abc\"}"))
                .andExpect(status().isUnauthorized())
                .andExpect(content().json("{\"detail\":\"登录状态已失效，请重新登录\"}", true));
    }

    @Test
    @DisplayName("用户名被占：409 照实说（这条本来就是给正在注册的人看的）")
    void registerRejectsTakenUsername() throws Exception {
        willThrow(new UsernameTakenException("alice"))
                .given(authService).register(eq("alice"), anyString(), anyString(), anyString());

        mvc.perform(post("/auth/register").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"username\":\"alice\",\"password\":\"pw123456\","
                                + "\"email\":\"alice@example.com\",\"code\":\"123456\"}"))
                .andExpect(status().isConflict())
                .andExpect(content().json("{\"detail\":\"用户名 alice 已被占用\"}", true));
    }

    @Test
    @DisplayName("GET /auth/me：身份只来自令牌，走一次库确认账号还在")
    void meReadsBackTheCaller() throws Exception {
        given(users.get("user-1")).willReturn(Optional.of(ALICE));

        mvc.perform(authed(get("/auth/me"), "user-1"))
                .andExpect(status().isOk())
                .andExpect(content().json(
                        "{\"id\":\"user-1\",\"username\":\"alice\",\"email\":\"alice@example.com\","
                                + "\"created_at\":\"2026-09-03T12:00:00+00:00\"}", true));
    }

    @Test
    @DisplayName("GET /auth/me 不带令牌：401，一次库都没查")
    void meRequiresIdentity() throws Exception {
        mvc.perform(get("/auth/me").contentType(MediaType.APPLICATION_JSON))
                .andExpect(status().isUnauthorized())
                .andExpect(content().json("{\"detail\":\"缺少访问令牌\"}", true));

        // 令牌里的 id 不会被请求参数顶掉：查的是 CALLER 那一个
        verifyNoInteractions(users);
    }

    @Test
    @DisplayName("令牌还在但账号已删：404 账号不存在（无状态令牌的已知窗口，在这里挡掉）")
    void meRejectsDeletedAccount() throws Exception {
        given(users.get("user-gone")).willReturn(Optional.empty());

        mvc.perform(authed(get("/auth/me"), "user-gone"))
                .andExpect(status().isNotFound())
                .andExpect(content().json("{\"detail\":\"账号不存在\"}", true));
    }

    @Test
    @DisplayName("POST /auth/logout：204 无 body，吊销的是令牌里的那个账号")
    void logoutRevokesTheCaller() throws Exception {
        mvc.perform(authed(post("/auth/logout"), "user-1"))
                .andExpect(status().isNoContent());

        // 谁的令牌就吊销谁：请求参数里没有、也不该有 userId
        verify(authService).logout("user-1");
    }

    private static MockHttpServletRequestBuilder authed(MockHttpServletRequestBuilder request, String userId) {
        request.requestAttr(JwtAuthFilter.ATTRIBUTE, new AuthenticatedUser(userId, "whoever"));
        return request;
    }
}
