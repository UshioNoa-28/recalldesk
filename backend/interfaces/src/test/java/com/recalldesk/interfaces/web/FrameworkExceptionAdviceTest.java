package com.recalldesk.interfaces.web;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.recalldesk.application.document.DocumentService;
import com.recalldesk.application.eval.EvalRunService;
import com.recalldesk.application.eval.EvalService;
import com.recalldesk.interfaces.security.AuthenticatedUser;
import com.recalldesk.interfaces.security.JwtAuthFilter;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;

/**
 * 框架级错误的信封测试：请求没进到路由时也必须给 {@code {"detail": ...}}，
 * 不能露出 Spring 的白标页（{timestamp,status,error,path}）。
 */
@WebMvcTest(controllers = {DocumentController.class, EvalController.class})
class FrameworkExceptionAdviceTest {

    @Autowired
    private MockMvc mvc;

    @MockitoBean
    private DocumentService documentService;

    @MockitoBean
    private EvalService evalService;

    @MockitoBean
    private EvalRunService evalRunService;

    @Test
    @DisplayName("未匹配的路径：404 {\"detail\":\"Not Found\"}")
    void unknownPath() throws Exception {
        mvc.perform(get("/no/such/route"))
                .andExpect(status().isNotFound())
                .andExpect(content().json("{\"detail\":\"Not Found\"}", true));
    }

    @Test
    @DisplayName("方法不支持：405 {\"detail\":\"Method Not Allowed\"}")
    void methodNotAllowed() throws Exception {
        mvc.perform(patch("/documents/doc-1"))
                .andExpect(status().isMethodNotAllowed())
                .andExpect(content().json("{\"detail\":\"Method Not Allowed\"}", true));
    }

    @Test
    @DisplayName("非法 JSON：422 json_invalid（type/loc/msg 与 FastAPI 对齐）")
    void invalidJson() throws Exception {
        // 带上身份：这条要钉的是「请求体读不出来」的信封，不是「没登录」——
        // 参数解析按签名顺序走，没身份会先撞 401，轮不到 body 转换
        mvc.perform(authed(post("/eval/testsets").contentType(MediaType.APPLICATION_JSON).content("{oops")))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(content().json("""
                        {"detail":[{"type":"json_invalid","loc":["body"],"msg":"JSON decode error",
                                    "input":{}}]}""", false));
    }

    private static <B extends MockHttpServletRequestBuilder> B authed(B request) {
        request.requestAttr(JwtAuthFilter.ATTRIBUTE, new AuthenticatedUser("user-alice", "alice"));
        return request;
    }
}
