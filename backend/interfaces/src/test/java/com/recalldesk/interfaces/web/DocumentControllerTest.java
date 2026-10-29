package com.recalldesk.interfaces.web;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.BDDMockito.given;
import static org.mockito.BDDMockito.willThrow;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.recalldesk.application.document.DocumentService;
import com.recalldesk.application.search.dto.SearchOutcome;
import com.recalldesk.domain.Page;
import com.recalldesk.domain.documents.Document;
import com.recalldesk.application.document.dto.DocumentContent;
import com.recalldesk.domain.exception.documents.DocumentNotFoundException;
import com.recalldesk.domain.documents.DocumentStatus;
import com.recalldesk.domain.retrieval.ChannelTrace;
import com.recalldesk.domain.retrieval.ChunkHit;
import com.recalldesk.domain.retrieval.ChunkRecord;
import com.recalldesk.application.search.dto.SearchProfile;
import com.recalldesk.interfaces.security.AuthenticatedUser;
import com.recalldesk.interfaces.security.JwtAuthFilter;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.MalformedInputException;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import com.recalldesk.domain.exception.indexing.EmptyContentException;

/**
 * 文档路由的 HTTP 契约测试。
 *
 * 422 的期望正文直接读 {@code src/test/resources/contract/*.json}——那是从跑起来的
 * 真实服务抓下来的响应，逐字节比较；
 * 成功分支的期望 JSON 手写（形状来自控制器与 DTO 定义，
 * 形状来自控制器源码与服务 dict 构造器）。
 *
 * 身份由 {@link JwtAuthFilter} 放进 request attribute，这里直接摆好那份身份、跳过验签
 * （过滤器自己有自己的用例）；要钉的是「caller.userId() 有没有递到服务」——
 * 少递一个参数就是越权，而 HTTP 层看不出来。
 */
@WebMvcTest(controllers = DocumentController.class)
class DocumentControllerTest {

    private static final String ALICE = "user-alice";
    private static final AuthenticatedUser CALLER = new AuthenticatedUser(ALICE, "alice");

    @Autowired
    private MockMvc mvc;

    @MockitoBean
    private DocumentService documentService;

    private static String contract(String name) throws IOException {
        try (InputStream stream = DocumentControllerTest.class.getResourceAsStream("/contract/" + name)) {
            return new String(stream.readAllBytes(), StandardCharsets.UTF_8);
        }
    }

    private static Document document(DocumentStatus status, Integer chunkCount, Instant indexedAt) {
        return new Document(
                "doc-1", ALICE, "notes.md", "uploads/doc-1", 12, "text/markdown",
                status, chunkCount, null, Instant.parse("2026-09-03T12:00:00Z"), indexedAt);
    }

    // ---- 身份 ----

    @Test
    @DisplayName("没有身份（过滤器没发过 attribute）：401 缺少访问令牌，服务一次都没被调用")
    void withoutIdentityIsUnauthorized() throws Exception {
        mvc.perform(get("/documents"))
                .andExpect(status().isUnauthorized())
                .andExpect(content().json("{\"detail\":\"缺少访问令牌\"}", true));

        verify(documentService, never()).list(any(), anyInt(), anyInt());
    }

    // ---- GET /search：参数校验的 422 信封 ----

    @Test
    @DisplayName("GET /search 缺 q：422 missing，body 逐字节钉住")
    void searchMissingQ() throws Exception {
        mvc.perform(authed(get("/search")))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(content().json(contract("search_missing_q.json"), true));
    }

    @Test
    @DisplayName("GET /search q 为空串：422 string_too_short")
    void searchEmptyQ() throws Exception {
        mvc.perform(authed(get("/search").param("q", "")))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(content().json(contract("search_empty_q.json"), true));
    }

    @Test
    @DisplayName("GET /search top_k 越界：422 greater_than_equal / less_than_equal")
    void searchTopKOutOfRange() throws Exception {
        mvc.perform(authed(get("/search").param("q", "豆腐").param("top_k", "0")))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(content().json(contract("search_topk_zero.json"), true));
        mvc.perform(authed(get("/search").param("q", "豆腐").param("top_k", "51")))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(content().json(contract("search_topk_51.json"), true));
    }

    @Test
    @DisplayName("GET /search 布尔参数写错：422 bool_parsing")
    void searchBadBoolean() throws Exception {
        mvc.perform(authed(get("/search").param("q", "x").param("rewrite", "maybe")))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(content().json(contract("search_bool_bad.json"), true));
    }

    @Test
    @DisplayName("GET /search：body 键序 query/hits，channels 只在 true 时出现")
    void searchOmitsChannelsByDefault() throws Exception {
        ChunkHit hit = new ChunkHit("doc-1", "notes.md", 0, 1, "豆腐", 0.9);
        given(documentService.search(eq("豆腐"), eq(null), eq(new SearchProfile(true, true, null)), eq(ALICE)))
                .willReturn(new SearchOutcome(List.of(hit), List.of(new ChannelTrace("dense_original", "豆腐", List.of(hit), 12))));

        mvc.perform(authed(get("/search").param("q", "豆腐")))
                .andExpect(status().isOk())
                .andExpect(content().json("""
                        {"query":"豆腐","hits":[{"document_id":"doc-1","document_name":"notes.md",
                        "chunk_index":0,"chunk_count":1,"text":"豆腐","score":0.9}]}""", true));
    }

    @Test
    @DisplayName("GET /search channels=true：追加 channels 键（kind/text/hits/took_ms）")
    void searchAddsChannelsWhenAsked() throws Exception {
        ChunkHit hit = new ChunkHit("doc-1", "notes.md", 0, 1, "豆腐", 0.9);
        given(documentService.search(eq("豆腐"), eq(3), eq(new SearchProfile(false, false, null)), eq(ALICE)))
                .willReturn(new SearchOutcome(List.of(hit), List.of(new ChannelTrace("dense_original", "豆腐", List.of(hit), 12))));

        mvc.perform(authed(get("/search").param("q", "豆腐").param("top_k", "3")
                        .param("rewrite", "false").param("rerank", "false").param("channels", "true")))
                .andExpect(status().isOk())
                .andExpect(content().json("""
                        {"query":"豆腐",
                         "hits":[{"document_id":"doc-1","document_name":"notes.md","chunk_index":0,
                                  "chunk_count":1,"text":"豆腐","score":0.9}],
                         "channels":[{"kind":"dense_original","text":"豆腐",
                                      "hits":[{"document_id":"doc-1","document_name":"notes.md","chunk_index":0,
                                               "chunk_count":1,"text":"豆腐","score":0.9}],"took_ms":12}]}""", true));
    }

    // ---- GET /documents ----

    @Test
    @DisplayName("GET /documents 分页参数越界/类型错：422")
    void listDocumentsValidation() throws Exception {
        mvc.perform(authed(get("/documents").param("page", "0")))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(content().json(contract("documents_page_zero.json"), true));
        mvc.perform(authed(get("/documents").param("page_size", "101")))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(content().json(contract("documents_pagesize_101.json"), true));
        mvc.perform(authed(get("/documents").param("page", "abc")))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(content().json(contract("documents_page_abc.json"), true));
    }

    @Test
    @DisplayName("GET /documents：items/total/page/page_size，时间按统一 isoformat")
    void listDocumentsShape() throws Exception {
        given(documentService.list(ALICE, 1, 20))
                .willReturn(new Page<>(List.of(document(DocumentStatus.SUCCESS, 3,
                        Instant.parse("2026-09-03T12:00:01.123456Z"))), 7));

        mvc.perform(authed(get("/documents")))
                .andExpect(status().isOk())
                .andExpect(content().json("""
                        {"items":[{"id":"doc-1","name":"notes.md","status":"success","chunk_count":3,
                                   "created_at":"2026-09-03T12:00:00+00:00",
                                   "indexed_at":"2026-09-03T12:00:01.123456+00:00","error_message":null}],
                         "total":7,"page":1,"page_size":20}""", true));
    }

    // ---- 详情 / 分块 / 原文 / 重索引 / 删除 ----

    @Test
    @DisplayName("GET /documents/{id}：_to_dict 键序，null 照旧输出")
    void detailShape() throws Exception {
        given(documentService.get(ALICE, "doc-1")).willReturn(document(DocumentStatus.PENDING, null, null));

        mvc.perform(authed(get("/documents/doc-1")))
                .andExpect(status().isOk())
                .andExpect(content().json("""
                        {"id":"doc-1","name":"notes.md","status":"pending","chunk_count":null,
                         "created_at":"2026-09-03T12:00:00+00:00","indexed_at":null,"error_message":null}""", true));
    }

    @Test
    @DisplayName("GET /documents/{id} 不存在（含别人的文档）：404 文档不存在")
    void detailNotFound() throws Exception {
        given(documentService.get(ALICE, "nope")).willThrow(new DocumentNotFoundException("nope"));
        // 服务把「不存在」与「不是你的」翻成同一个异常，路由层没有第二条分支可写错

        mvc.perform(authed(get("/documents/nope")))
                .andExpect(status().isNotFound())
                .andExpect(content().json("{\"detail\":\"文档不存在\"}", true));
    }

    @Test
    @DisplayName("GET /documents/{id}/chunks：document_id/total_chunks/chunks（块字段保序）")
    void chunksShape() throws Exception {
        given(documentService.chunks(ALICE, "doc-1")).willReturn(List.of(new ChunkRecord("doc-1", 0, "第一块", "notes.md", 2)));

        mvc.perform(authed(get("/documents/doc-1/chunks")))
                .andExpect(status().isOk())
                .andExpect(content().json("""
                        {"document_id":"doc-1","total_chunks":1,
                         "chunks":[{"document_id":"doc-1","chunk_index":0,"text":"第一块",
                                    "document_name":"notes.md","chunk_count":2}]}""", true));
    }

    @Test
    @DisplayName("GET /documents/{id}/content：text/plain;charset=UTF-8，download 才带附件头")
    void contentShape() throws Exception {
        given(documentService.content(ALICE, "doc-1")).willReturn(new DocumentContent("notes.md", "正文"));

        mvc.perform(authed(get("/documents/doc-1/content")))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith(new MediaType("text", "plain", StandardCharsets.UTF_8)))
                .andExpect(content().string("正文"))
                .andExpect(header().doesNotExist("Content-Disposition"));

        mvc.perform(authed(get("/documents/doc-1/content").param("download", "true")))
                .andExpect(status().isOk())
                .andExpect(header().string("Content-Disposition", "attachment; filename=\"notes.md\""));
    }

    @Test
    @DisplayName("POST /documents/{id}/reindex：document_id/name/status；PENDING 时 400")
    void reindexShapeAndConflict() throws Exception {
        given(documentService.reindex(ALICE, "doc-1")).willReturn(document(DocumentStatus.PENDING, null, null));

        mvc.perform(authed(post("/documents/doc-1/reindex")))
                .andExpect(status().isOk())
                .andExpect(content().json("{\"document_id\":\"doc-1\",\"name\":\"notes.md\",\"status\":\"pending\"}", true));

        given(documentService.reindex(ALICE, "busy"))
                .willThrow(new IllegalArgumentException("文档正在处理中，完成或失败后再重新索引"));
        mvc.perform(authed(post("/documents/busy/reindex")))
                .andExpect(status().isBadRequest())
                .andExpect(content().json("{\"detail\":\"文档正在处理中，完成或失败后再重新索引\"}", true));
    }

    @Test
    @DisplayName("DELETE /documents/{id}：document_id/deleted/removed_eval_items；不存在 404")
    void deleteShapeAndNotFound() throws Exception {
        given(documentService.delete(ALICE, "doc-1")).willReturn(3);

        mvc.perform(authed(delete("/documents/doc-1")))
                .andExpect(status().isOk())
                .andExpect(content().json(
                        "{\"document_id\":\"doc-1\",\"deleted\":true,\"removed_eval_items\":3}", true));

        // 没有连带清题时也是这个键（0 而不是缺键）：调用方不必区分「没题」与「旧版本响应」
        given(documentService.delete(ALICE, "doc-2")).willReturn(0);
        String body = mvc.perform(authed(delete("/documents/doc-2")))
                .andExpect(status().isOk())
                .andReturn().getResponse().getContentAsString();
        assertThat(body).contains("\"removed_eval_items\":0");

        willThrow(new DocumentNotFoundException("nope")).given(documentService).delete(ALICE, "nope");
        mvc.perform(authed(delete("/documents/nope")))
                .andExpect(status().isNotFound())
                .andExpect(content().json("{\"detail\":\"文档不存在\"}", true));
    }

    // ---- POST /documents：上传 ----

    @Test
    @DisplayName("POST /documents 没有 file 段：422")
    void uploadNoFile() throws Exception {
        mvc.perform(authed(multipart("/documents")))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(content().json(contract("upload_no_file.json"), true));
    }

    @Test
    @DisplayName("POST /documents 成功：document_id/name/status，归属从身份里来")
    void uploadSuccess() throws Exception {
        given(documentService.ingest(eq("notes.md"), any(), eq("text/markdown"), eq(ALICE)))
                .willReturn(document(DocumentStatus.PENDING, null, null));

        mvc.perform(authed(multipart("/documents")
                        .file(new MockMultipartFile("file", "notes.md", "text/markdown", "内容".getBytes(StandardCharsets.UTF_8)))))
                .andExpect(status().isOk())
                .andExpect(content().json("{\"document_id\":\"doc-1\",\"name\":\"notes.md\",\"status\":\"pending\"}", true));
    }

    @Test
    @DisplayName("POST /documents 后缀不在白名单：400 不支持的文件类型（只收 txt/md）")
    void uploadUnsupportedSuffix() throws Exception {
        mvc.perform(authed(multipart("/documents")
                        .file(new MockMultipartFile("file", "old.pdf", "application/pdf", "%PDF".getBytes(StandardCharsets.UTF_8)))))
                .andExpect(status().isBadRequest())
                .andExpect(content().json("{\"detail\":\"不支持的文件类型: .pdf\"}", true));
    }

    @Test
    @DisplayName("POST /documents 空文件：400 文件内容为空")
    void uploadEmptyFile() throws Exception {
        mvc.perform(authed(multipart("/documents")
                        .file(new MockMultipartFile("file", "empty.txt", "text/plain", new byte[0]))))
                .andExpect(status().isBadRequest())
                .andExpect(content().json("{\"detail\":\"文件内容为空\"}", true));
    }

    @Test
    @DisplayName("POST /documents 超过 10MiB：413 文件过大")
    void uploadTooLarge() throws Exception {
        mvc.perform(authed(multipart("/documents")
                        .file(new MockMultipartFile("file", "big.txt", "text/plain", new byte[10 * 1024 * 1024 + 1]))))
                .andExpect(status().isPayloadTooLarge())
                .andExpect(content().json("{\"detail\":\"文件过大\"}", true));
    }

    @Test
    @DisplayName("POST /documents 非 UTF-8：400 文件必须是 UTF-8 文本（与普通 ValueError 分档）")
    void uploadInvalidUtf8() throws Exception {
        CharacterCodingException malformed = new MalformedInputException(1);
        given(documentService.ingest(any(), any(), any(), any()))
                .willThrow(new IllegalArgumentException("文件不是合法的 UTF-8 文本", malformed));

        mvc.perform(authed(multipart("/documents")
                        .file(new MockMultipartFile("file", "bad.txt", "text/plain", new byte[] {(byte) 0xff}))))
                .andExpect(status().isBadRequest())
                .andExpect(content().json("{\"detail\":\"文件必须是 UTF-8 文本\"}", true));
    }

    @Test
    @DisplayName("POST /documents 切不出块：400 用服务原话")
    void uploadEmptyContent() throws Exception {
        given(documentService.ingest(any(), any(), any(), any()))
                .willThrow(new EmptyContentException("文档内容切不出任何分块，无法索引"));

        mvc.perform(authed(multipart("/documents")
                        .file(new MockMultipartFile("file", "notes.md", "text/markdown", "内容".getBytes(StandardCharsets.UTF_8)))))
                .andExpect(status().isBadRequest())
                .andExpect(content().json("{\"detail\":\"文档内容切不出任何分块，无法索引\"}", true));
    }

    @Test
    @DisplayName("POST /documents 其它异常：500 索引失败: {exc}")
    void uploadUnexpectedFailure() throws Exception {
        given(documentService.ingest(any(), any(), any(), any())).willThrow(new IllegalStateException("db gone"));

        mvc.perform(authed(multipart("/documents")
                        .file(new MockMultipartFile("file", "notes.md", "text/markdown", "内容".getBytes(StandardCharsets.UTF_8)))))
                .andExpect(status().isInternalServerError())
                .andExpect(content().json("{\"detail\":\"索引失败: db gone\"}", true));
    }

    private MockHttpServletRequestBuilder uploadFile() {
        return multipart("/documents")
                .file(new MockMultipartFile("file", "notes.md", "text/markdown", "内容".getBytes(StandardCharsets.UTF_8)));
    }

    /** 把已验过的身份摆进请求：验签本身是 {@link JwtAuthFilter} 的用例，不在这儿重跑。 */
    private static <B extends MockHttpServletRequestBuilder> B authed(B request) {
        request.requestAttr(JwtAuthFilter.ATTRIBUTE, CALLER);
        return request;
    }
}
