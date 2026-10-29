package com.recalldesk.interfaces.web;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.BDDMockito.given;
import static org.mockito.BDDMockito.willThrow;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.recalldesk.application.eval.EvalRunService;
import com.recalldesk.application.eval.EvalService;
import com.recalldesk.domain.eval.ChannelScore;
import com.recalldesk.domain.eval.EvalRun;
import com.recalldesk.domain.eval.EvalRunConfig;
import com.recalldesk.application.eval.dto.EvalRunDetail;
import com.recalldesk.domain.eval.EvalRunItem;
import com.recalldesk.application.eval.dto.EvalRunItemDto;
import com.recalldesk.domain.eval.EvalRunStatus;
import com.recalldesk.domain.eval.EvalTestSet;
import com.recalldesk.application.eval.dto.EvalTestSetDetail;
import com.recalldesk.domain.eval.EvalTestSetItem;
import com.recalldesk.domain.eval.EvidenceQuote;
import com.recalldesk.application.eval.dto.ImportedQuestion;
import com.recalldesk.application.eval.dto.ImportedQuestion.ImportedChunk;
import com.recalldesk.domain.exception.eval.RunNotFoundException;
import com.recalldesk.domain.exception.eval.TestSetNotFoundException;
import com.recalldesk.domain.retrieval.FusionConfig;
import com.recalldesk.interfaces.security.AuthenticatedUser;
import com.recalldesk.interfaces.security.JwtAuthFilter;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;

/**
 * 评测路由的 HTTP 契约测试（9 条）。
 *
 * 422 的期望正文读 {@code src/test/resources/contract/*.json}——抓自真实服务的响应；
 * 成功分支的期望 JSON 手写（形状来自控制器与 DTO 定义）。
 * 201/202 单独断言：那是契约的一部分。
 *
 * 形状由「题目由用户上传、由引文判分」决定：加题是 multipart 传 jsonl，
 * 集合上没有出题状态与进度，证据给的是引文原文加它的解析落点。
 */
@WebMvcTest(controllers = EvalController.class)
class EvalControllerTest {

    private static final String ALICE = "user-alice";
    private static final AuthenticatedUser CALLER = new AuthenticatedUser(ALICE, "alice");
    private static final Instant CREATED = Instant.parse("2026-09-03T12:00:00Z");
    private static final Instant RESOLVED = Instant.parse("2026-09-03T12:00:01Z");

    @Autowired
    private MockMvc mvc;

    @MockitoBean
    private EvalService evalService;

    @MockitoBean
    private EvalRunService evalRunService;

    private static String contract(String name) throws IOException {
        try (InputStream stream = EvalControllerTest.class.getResourceAsStream("/contract/" + name)) {
            return new String(stream.readAllBytes(), StandardCharsets.UTF_8);
        }
    }

    private static EvalTestSet testSet() {
        return new EvalTestSet("ts-1", ALICE, "水果题集", 1, CREATED);
    }

    private static EvalTestSetItem item() {
        return new EvalTestSetItem("item-1", "苹果有什么营养？", List.of(
                new EvidenceQuote("ev-1", "item-1", "doc-1", 0, 0),
                new EvidenceQuote("ev-2", "item-1", "doc-2", 4, 1)));
    }

    private static EvalTestSetDetail detail() {
        return new EvalTestSetDetail(testSet(), List.of(item()));
    }

    private static EvalRun run(EvalRunStatus status) {
        return new EvalRun(
                "run-1", ALICE, "ts-1", status, new EvalRunConfig(5, false, true, null),
                Map.of("queries", 1), null, CREATED, null, 0, 1);
    }

    private static EvalRunItemDto runItemView() {
        return EvalRunItemDto.of(new EvalRunItem(
                "item-1", "苹果有什么营养？", 1, 12.5, 1, 1, List.of(1),
                List.of(new ChannelScore("dense_original", "苹果有什么营养？", List.of(1), 12L))));
    }

    /** 一行一题的 jsonl：两题，形状都合法。 */
    private static MockMultipartFile questions() {
        return new MockMultipartFile(
                "file", "questions.jsonl", "application/x-ndjson",
                ("{\"query\":\"第一题\",\"evidence\":[{\"document_id\":\"doc-1\",\"chunk_index\":0}]}\n"
                        + "{\"query\":\"第二题\",\"evidence\":[{\"document_id\":\"doc-2\",\"chunk_index\":1},"
                        + "{\"document_id\":\"doc-3\",\"chunk_index\":2}]}\n")
                        .getBytes(StandardCharsets.UTF_8));
    }

    private static MockMultipartFile questions(String content) {
        return new MockMultipartFile("file", "questions.jsonl", "application/x-ndjson", content.getBytes(StandardCharsets.UTF_8));
    }

    // ---- 身份 ----

    @Test
    @DisplayName("没有身份：401 缺少访问令牌，服务一次都没被调用")
    void withoutIdentityIsUnauthorized() throws Exception {
        mvc.perform(get("/eval/testsets"))
                .andExpect(status().isUnauthorized())
                .andExpect(content().json("{\"detail\":\"缺少访问令牌\"}", true));

        verify(evalService, never()).listTestSets(any());
    }

    // ---- POST /eval/testsets（201） ----

    @Test
    @DisplayName("POST /eval/testsets：201，摊平的 testset + items，归属取自身份")
    void createTestSet() throws Exception {
        given(evalService.createTestSet(ALICE, null)).willReturn(new EvalTestSetDetail(testSet(), List.of()));

        mvc.perform(authed(post("/eval/testsets").contentType(MediaType.APPLICATION_JSON).content("{\"name\":null}")))
                .andExpect(status().isCreated())
                .andExpect(content().json("""
                        {"id":"ts-1","name":"水果题集","item_count":1,
                         "created_at":"2026-09-03T12:00:00+00:00","items":[]}""", true));
    }

    @Test
    @DisplayName("POST /eval/testsets 没有 body：422 missing")
    void createTestSetNoBody() throws Exception {
        mvc.perform(authed(post("/eval/testsets")))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(content().json(contract("ts_no_body.json"), true));
    }

    @Test
    @DisplayName("POST /eval/testsets name 超长：422，文案写明上限")
    void createTestSetNameTooLong() throws Exception {
        String body = mvc.perform(authed(post("/eval/testsets").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"name\":\"" + "x".repeat(256) + "\"}")))
                .andExpect(status().isUnprocessableEntity())
                .andReturn().getResponse().getContentAsString();

        assertThat(body).contains("名称最长 255 个字符");
        verifyNoInteractions(evalService);
    }

    // ---- POST /eval/testsets/{id}/items（上传 jsonl） ----

    @Test
    @DisplayName("上传题目：两行两题，逐行立成 ImportedQuestion 后连身份一起递给服务")
    void uploadItemsParsesEveryLine() throws Exception {
        given(evalService.importItems(eq(ALICE), eq("ts-1"), anyList())).willReturn(detail());

        mvc.perform(authed(multipart("/eval/testsets/ts-1/items").file(questions())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.item_count").value(1))
                .andExpect(jsonPath("$.items[0].evidence[0].chunk_index").value(0));

        verify(evalService).importItems(ALICE, "ts-1", List.of(
                new ImportedQuestion("第一题", List.of(new ImportedChunk("doc-1", 0))),
                new ImportedQuestion("第二题", List.of(
                        new ImportedChunk("doc-2", 1), new ImportedChunk("doc-3", 2)))));
    }

    @Test
    @DisplayName("出参两键：document_id / chunk_index")
    void uploadItemsReturnsEvidenceShape() throws Exception {
        given(evalService.importItems(eq(ALICE), eq("ts-1"), anyList())).willReturn(detail());

        mvc.perform(authed(multipart("/eval/testsets/ts-1/items").file(questions())))
                .andExpect(status().isOk())
                .andExpect(content().json("""
                        {"id":"ts-1","name":"水果题集","item_count":1,
                         "created_at":"2026-09-03T12:00:00+00:00",
                         "items":[{"id":"item-1","query":"苹果有什么营养？",
                                   "evidence":[
                                     {"document_id":"doc-1","chunk_index":0},
                                     {"document_id":"doc-2","chunk_index":4}]}]}""", true));
    }

    @Test
    @DisplayName("没有 file 段：422 missing body.file（与上传文档同一份 golden）")
    void uploadItemsWithoutFile() throws Exception {
        mvc.perform(authed(multipart("/eval/testsets/ts-1/items")))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(content().json(contract("upload_no_file.json"), true));
    }

    @Test
    @DisplayName("后缀不是 .jsonl：400 只接受 .jsonl（把整份 .json 数组拍平传上来是常见误用）")
    void uploadItemsRejectsOtherSuffix() throws Exception {
        MockMultipartFile json = new MockMultipartFile(
                "file", "questions.json", "application/json", "{}".getBytes(StandardCharsets.UTF_8));

        mvc.perform(authed(multipart("/eval/testsets/ts-1/items").file(json)))
                .andExpect(status().isBadRequest())
                .andExpect(content().json("{\"detail\":\"题目文件只接受 .jsonl（当前: .json）\"}", true));
    }

    @Test
    @DisplayName("空文件 400、超过 2MiB 413：形状问题不该走到解析与落库")
    void uploadItemsFileSize() throws Exception {
        mvc.perform(authed(multipart("/eval/testsets/ts-1/items")
                        .file(new MockMultipartFile("file", "q.jsonl", "application/x-ndjson", new byte[0]))))
                .andExpect(status().isBadRequest())
                .andExpect(content().json("{\"detail\":\"文件内容为空\"}", true));

        mvc.perform(authed(multipart("/eval/testsets/ts-1/items")
                        .file(new MockMultipartFile(
                                "file", "q.jsonl", "application/x-ndjson", new byte[2 * 1024 * 1024 + 1]))))
                .andExpect(status().isPayloadTooLarge())
                .andExpect(content().json("{\"detail\":\"文件过大\"}", true));
    }

    @Test
    @DisplayName("行形状读不出来：400 按行列出问题，一行坏不等于整份只报第一条")
    void uploadItemsReportsEveryBadLine() throws Exception {
        String body = mvc.perform(authed(multipart("/eval/testsets/ts-1/items")
                        .file(questions("{\"query\":\"第一题\",\"evidence\":[{\"document_id\":\"d\",\"chunk_index\":0}]}\n"
                                + "{\"query\":\"第二题\",\"quotes\":[{\"document_id\":\"d\"}]}\n"))))
                .andExpect(status().isBadRequest())
                .andReturn().getResponse().getContentAsString();

        assertThat(body).contains("题目文件读不出来");
        // 第 2 行既打错了键（quotes）又缺 evidence，两条都要说出来，否则用户只改一条还得再传一次
        assertThat(body).contains("第 2 行 有不认识的键：quotes");
        assertThat(body).contains("第 2 行 缺 evidence");
        verify(evalService, never()).importItems(any(), any(), anyList());
    }

    @Test
    @DisplayName("非 UTF-8 的 jsonl：400 文件必须是 UTF-8 文本（与文档上传同一句文案）")
    void uploadItemsRejectsBadEncoding() throws Exception {
        MockMultipartFile latin1 = new MockMultipartFile(
                "file", "q.jsonl", "application/x-ndjson", new byte[] {'{', (byte) 0xff, '}'});

        String body = mvc.perform(authed(multipart("/eval/testsets/ts-1/items").file(latin1)))
                .andExpect(status().isBadRequest())
                .andReturn().getResponse().getContentAsString();

        assertThat(body).contains("题目文件读不出来").contains("文件必须是 UTF-8 文本");
    }

    @Test
    @DisplayName("评测集不存在 404；引文对不上 400 用服务原话（整份拒绝的清单由服务拼）")
    void uploadItemsErrors() throws Exception {
        given(evalService.importItems(eq(ALICE), eq("nope"), anyList()))
                .willThrow(new TestSetNotFoundException("nope"));
        mvc.perform(authed(multipart("/eval/testsets/nope/items").file(questions())))
                .andExpect(status().isNotFound())
                .andExpect(content().json("{\"detail\":\"评测集不存在\"}", true));

        given(evalService.importItems(eq(ALICE), eq("ts-1"), anyList()))
                .willThrow(new IllegalArgumentException("导入失败，共 1 道题有问题：\n1. 第 1 题（第一题）的引文「第一段话」在文档「a.txt」里找不到原样出现的位置"));
        mvc.perform(authed(multipart("/eval/testsets/ts-1/items").file(questions())))
                .andExpect(status().isBadRequest())
                .andExpect(content().json("""
                        {"detail":"导入失败，共 1 道题有问题：\\n1. 第 1 题（第一题）的引文「第一段话」在文档「a.txt」里找不到原样出现的位置"}""", true));
    }

    // ---- 列表 / 详情 / 删除 ----

    @Test
    @DisplayName("GET /eval/testsets：{\"testsets\": [...]}，只有 item_count，没有出题状态")
    void listTestSets() throws Exception {
        given(evalService.listTestSets(ALICE)).willReturn(List.of(testSet()));

        mvc.perform(authed(get("/eval/testsets")))
                .andExpect(status().isOk())
                .andExpect(content().json("""
                        {"testsets":[{"id":"ts-1","name":"水果题集","item_count":1,
                                      "created_at":"2026-09-03T12:00:00+00:00"}]}""", true));
    }

    @Test
    @DisplayName("GET /eval/testsets/{id}：摊平元信息 + items；不存在 404")
    void getTestSet() throws Exception {
        given(evalService.getTestSet(ALICE, "ts-1")).willReturn(detail());

        mvc.perform(authed(get("/eval/testsets/ts-1")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items[0].evidence[1].chunk_index").value(4))
                .andExpect(jsonPath("$.items[0].evidence[0].document_id").value("doc-1"));

        given(evalService.getTestSet(ALICE, "nope")).willThrow(new TestSetNotFoundException("nope"));
        mvc.perform(authed(get("/eval/testsets/nope")))
                .andExpect(status().isNotFound())
                .andExpect(content().json("{\"detail\":\"评测集不存在\"}", true));
    }

    @Test
    @DisplayName("DELETE /eval/testsets/{id}：testset_id/deleted；不存在 404")
    void deleteTestSet() throws Exception {
        mvc.perform(authed(delete("/eval/testsets/ts-1")))
                .andExpect(status().isOk())
                .andExpect(content().json("{\"testset_id\":\"ts-1\",\"deleted\":true}", true));
        verify(evalService).deleteTestSet(ALICE, "ts-1");

        willThrow(new TestSetNotFoundException("nope")).given(evalService).deleteTestSet(ALICE, "nope");
        mvc.perform(authed(delete("/eval/testsets/nope")))
                .andExpect(status().isNotFound())
                .andExpect(content().json("{\"detail\":\"评测集不存在\"}", true));
    }

    // ---- POST /eval/testsets/{id}/runs（202） ----

    @Test
    @DisplayName("开 run：不带 body → 默认全开 + 默认融合档（null）；202 + 摊平 run + items")
    void startRunDefaults() throws Exception {
        given(evalRunService.startRun(ALICE, "ts-1", null, true, true, null))
                .willReturn(new EvalRunDetail(run(EvalRunStatus.RUNNING), List.of(runItemView())));

        mvc.perform(authed(post("/eval/testsets/ts-1/runs")))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.id").value("run-1"))
                .andExpect(jsonPath("$.status").value("running"))
                .andExpect(jsonPath("$.config.fusion").doesNotExist())
                .andExpect(jsonPath("$.items[0].testset_item_id").value("item-1"))
                .andExpect(jsonPath("$.items[0].recall").value(1));
    }

    @Test
    @DisplayName("开 run：请求体里的三个开关与 partial 融合配方原样传下去")
    void startRunForwardsRecipe() throws Exception {
        given(evalRunService.startRun(ALICE, "ts-1", 5, false, false,
                        new FusionConfig("weighted", null, null, Map.of("sparse", 2.0))))
                .willReturn(new EvalRunDetail(run(EvalRunStatus.RUNNING), List.of()));

        mvc.perform(authed(post("/eval/testsets/ts-1/runs").contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"top_k":5,"query_rewrite":false,"rerank":false,
                                 "fusion":{"method":"weighted","weights":{"sparse":2.0}}}""")))
                .andExpect(status().isAccepted());

        verify(evalRunService).startRun(ALICE, "ts-1", 5, false, false,
                new FusionConfig("weighted", null, null, Map.of("sparse", 2.0)));
    }

    @Test
    @DisplayName("开 run：top_k / fusion 越界 → 422，注解在进服务前拦下")
    void startRunValidation() throws Exception {
        String topK = mvc.perform(authed(post("/eval/testsets/x/runs").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"top_k\":0}")))
                .andExpect(status().isUnprocessableEntity())
                .andReturn().getResponse().getContentAsString();
        assertThat(topK).contains("top_k 需在 1-50 之间");

        String fusion = mvc.perform(authed(post("/eval/testsets/x/runs").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"fusion\":{\"method\":\"foo\"}}")))
                .andExpect(status().isUnprocessableEntity())
                .andReturn().getResponse().getContentAsString();
        assertThat(fusion).contains("fusion.method 只能是 rrf 或 weighted");

        verifyNoInteractions(evalRunService);
    }

    @Test
    @DisplayName("开 run：测试集不存在 404；引文坐标失效 400 用服务原话")
    void startRunErrors() throws Exception {
        given(evalRunService.startRun(eq(ALICE), eq("nope"), any(), any(Boolean.class), any(Boolean.class), any()))
                .willThrow(new TestSetNotFoundException("nope"));
        mvc.perform(authed(post("/eval/testsets/nope/runs")))
                .andExpect(status().isNotFound())
                .andExpect(content().json("{\"detail\":\"评测集不存在\"}", true));

        given(evalRunService.startRun(eq(ALICE), eq("ts-1"), any(), any(Boolean.class), any(Boolean.class), any()))
                .willThrow(new IllegalArgumentException(
                        "评测集的证据坐标已失效，先修正再跑：\n1. 「第一段话」在文档 a.txt 的当前分块里找不到了"));
        mvc.perform(authed(post("/eval/testsets/ts-1/runs")))
                .andExpect(status().isBadRequest())
                .andExpect(content().json("""
                        {"detail":"评测集的证据坐标已失效，先修正再跑：\\n1. 「第一段话」在文档 a.txt 的当前分块里找不到了"}""", true));
    }

    // ---- 历史 runs / rerun / 详情 ----

    @Test
    @DisplayName("GET /eval/testsets/{id}/runs：{\"runs\": [...]}，键序同 _run_dict")
    void listRuns() throws Exception {
        given(evalRunService.listRuns(ALICE, "ts-1")).willReturn(List.of(run(EvalRunStatus.DONE)));

        mvc.perform(authed(get("/eval/testsets/ts-1/runs")))
                .andExpect(status().isOk())
                .andExpect(content().json("""
                        {"runs":[{"id":"run-1","testset_id":"ts-1","status":"done",
                                  "config":{"top_k":5,"query_rewrite":false,"rerank":true,"fusion":null},
                                  "metrics":{"queries":1},"error_message":null,"progress_done":0,
                                  "progress_total":1,"created_at":"2026-09-03T12:00:00+00:00",
                                  "finished_at":null}]}""", true));

        given(evalRunService.listRuns(ALICE, "nope")).willThrow(new TestSetNotFoundException("nope"));
        mvc.perform(authed(get("/eval/testsets/nope/runs")))
                .andExpect(status().isNotFound())
                .andExpect(content().json("{\"detail\":\"评测集不存在\"}", true));
    }

    @Test
    @DisplayName("POST /eval/runs/{id}/rerun_failed：200；不存在 404；不是 failed 400")
    void rerunFailed() throws Exception {
        given(evalRunService.rerunFailed(ALICE, "run-1"))
                .willReturn(new EvalRunDetail(run(EvalRunStatus.RUNNING), List.of()));

        mvc.perform(authed(post("/eval/runs/run-1/rerun_failed")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value("run-1"));

        given(evalRunService.rerunFailed(ALICE, "nope")).willThrow(new RunNotFoundException("nope"));
        mvc.perform(authed(post("/eval/runs/nope/rerun_failed")))
                .andExpect(status().isNotFound())
                .andExpect(content().json("{\"detail\":\"评测运行不存在\"}", true));

        given(evalRunService.rerunFailed(ALICE, "busy"))
                .willThrow(new IllegalArgumentException("只有失败的运行可以重跑失败题"));
        mvc.perform(authed(post("/eval/runs/busy/rerun_failed")))
                .andExpect(status().isBadRequest())
                .andExpect(content().json("{\"detail\":\"只有失败的运行可以重跑失败题\"}", true));
    }

    @Test
    @DisplayName("GET /eval/runs/{id}：摊平 run + items（派生指标现算，逐通道明细带上）；不存在 404")
    void getRun() throws Exception {
        given(evalRunService.getRun(ALICE, "run-1"))
                .willReturn(new EvalRunDetail(run(EvalRunStatus.DONE), List.of(runItemView())));

        mvc.perform(authed(get("/eval/runs/run-1")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items[0].testset_item_id").value("item-1"))
                .andExpect(jsonPath("$.items[0].evidence_ranks[0]").value(1))
                .andExpect(jsonPath("$.items[0].recall").value(1))
                .andExpect(jsonPath("$.items[0].evidence_coverage").value(1.0))
                .andExpect(jsonPath("$.items[0].channels[0].kind").value("dense_original"))
                .andExpect(jsonPath("$.items[0].channels[0].recall").value(1))
                .andExpect(jsonPath("$.items[0].channels[0].took_ms").value(12));

        given(evalRunService.getRun(ALICE, "nope")).willThrow(new RunNotFoundException("nope"));
        mvc.perform(authed(get("/eval/runs/nope")))
                .andExpect(status().isNotFound())
                .andExpect(content().json("{\"detail\":\"评测运行不存在\"}", true));
    }

    /** 把已验过的身份摆进请求：验签本身是 {@link JwtAuthFilter} 的用例，不在这儿重跑。 */
    private static <B extends MockHttpServletRequestBuilder> B authed(B request) {
        request.requestAttr(JwtAuthFilter.ATTRIBUTE, CALLER);
        return request;
    }
}
