package com.recalldesk.interfaces.web;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.recalldesk.application.eval.EvalRunService;
import com.recalldesk.application.eval.EvalService;
import com.recalldesk.application.eval.dto.EvalRunDetail;
import com.recalldesk.application.eval.dto.EvalTestSetDetail;
import com.recalldesk.domain.eval.EvalRun;
import com.recalldesk.domain.eval.EvalTestSet;
import com.recalldesk.domain.eval.EvalTestSetItem;
import com.recalldesk.domain.eval.EvidenceQuote;
import com.recalldesk.application.eval.dto.ImportedQuestion;
import com.recalldesk.domain.retrieval.FusionConfig;
import com.recalldesk.interfaces.security.AuthenticatedUser;
import com.recalldesk.interfaces.web.dto.EvalDtos.CreateRunRequest;
import com.recalldesk.interfaces.web.dto.EvalDtos.CreateTestSetRequest;
import com.recalldesk.interfaces.web.dto.EvalDtos.EvidenceView;
import com.recalldesk.interfaces.web.dto.EvalDtos.FusionRequest;
import com.recalldesk.interfaces.web.dto.EvalDtos.ItemView;
import com.recalldesk.interfaces.web.dto.EvalDtos.RunDetail;
import com.recalldesk.interfaces.web.dto.EvalDtos.RunList;
import com.recalldesk.interfaces.web.dto.EvalDtos.RunView;
import com.recalldesk.interfaces.web.dto.EvalDtos.TestSetDeleted;
import com.recalldesk.interfaces.web.dto.EvalDtos.TestSetDetail;
import com.recalldesk.interfaces.web.dto.EvalDtos.TestSetList;
import com.recalldesk.interfaces.web.dto.EvalDtos.TestSetView;
import jakarta.validation.Valid;
import java.io.IOException;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

/**
 * 评测路由：9 条，全部要求 access 令牌且只看调用方自己的集合与运行。
 *
 * 加题这一条是结构性的：不再是
 * 「勾选块坐标 → 后台 LLM 出题」，而是上传一份 jsonl 题目文件，同步解析引文后落库
 * （{@code retry_failed_items} 随出题链一起没了）。出参因此不再有 status 与出题进度。
 *
 * 依旧只做契约搬运：请求体校验（pydantic 的 422 信封）、jsonl 的行形状、把服务返回值翻成
 * dict 形状、把异常翻成对应状态码与 detail。建集 201、开 run 202 是契约的一部分。
 */
@RestController
public class EvalController {

    /** 题目文件的后缀：jsonl 之外一律拒，免得把整份 .json 数组当逐行文件读进来。 */
    private static final List<String> ALLOWED_SUFFIXES = List.of(".jsonl");
    /** 一次上传的文件上限 2 MiB：500 道题的引文也就几十 KB，给不满是防手滑传了原始语料。 */
    private static final long MAX_UPLOAD_BYTES = 2L * 1024 * 1024;

    private final EvalService evalService;
    private final EvalRunService evalRunService;
    private final ObjectMapper objectMapper;

    public EvalController(
            EvalService evalService,
            EvalRunService evalRunService,
            ObjectMapper objectMapper) {
        this.evalService = evalService;
        this.evalRunService = evalRunService;
        this.objectMapper = objectMapper;
    }

    /** 创建一个空的评测集（201）：题目靠上传文件往里加。 */
    @PostMapping("/eval/testsets")
    public ResponseEntity<TestSetDetail> createTestSet(
            AuthenticatedUser caller, @Valid @RequestBody(required = false) CreateTestSetRequest request) {
        if (request == null) {
            throw missingBody();
        }
        return ResponseEntity.status(HttpStatus.CREATED)
                .contentType(MediaType.APPLICATION_JSON)
                .body(testSetDetail(evalService.createTestSet(caller.userId(), request.name())));
    }

    /**
     * 上传题目文件（jsonl，一行一题）：同一个请求内解析引文、落库、返回最新详情。
     *
     * 行形状问题（JSON 坏了、缺键、键名打错）在解析阶段收齐一起报，语义问题（文档不是你的、
     * 引文找不到）由 EvalService 汇总后报，两条都是 400 整份拒——半收半丢会让评测集的分母
     * 变成没人能对得上的数字。
     */
    @PostMapping("/eval/testsets/{testset_id}/items")
    public TestSetDetail uploadItems(
            AuthenticatedUser caller,
            @PathVariable("testset_id") String testSetId,
            @RequestParam(name = "file", required = false) MultipartFile file) {
        if (file == null) {
            FastApiValidation.Errors errors = new FastApiValidation.Errors();
            errors.add(FastApiValidation.missing(List.of("body", "file")));
            errors.throwIfAny();
        }
        validateUpload(file);
        QuestionJsonl.Parsed parsed = QuestionJsonl.parse(objectMapper, readBytes(file));
        if (!parsed.problems().isEmpty()) {
            throw new ApiError(400, QuestionJsonl.describe(parsed.problems()));
        }
        List<ImportedQuestion> questions = parsed.questions();
        return testSetDetail(evalService.importItems(caller.userId(), testSetId, questions));
    }

    /** 列出自己的评测集（含题目数）。 */
    @GetMapping("/eval/testsets")
    public TestSetList listTestSets(AuthenticatedUser caller) {
        return new TestSetList(evalService.listTestSets(caller.userId()).stream()
                .map(EvalController::testSetView)
                .toList());
    }

    /** 评测集详情：元信息 + 全部题目（每题带它的引文与解析落点）。 */
    @GetMapping("/eval/testsets/{testset_id}")
    public TestSetDetail getTestSet(AuthenticatedUser caller, @PathVariable("testset_id") String testSetId) {
        return testSetDetail(evalService.getTestSet(caller.userId(), testSetId));
    }

    /** 删除评测集：题目、引文与它名下所有 run 随级联一起走。 */
    @DeleteMapping("/eval/testsets/{testset_id}")
    public TestSetDeleted deleteTestSet(AuthenticatedUser caller, @PathVariable("testset_id") String testSetId) {
        evalService.deleteTestSet(caller.userId(), testSetId);
        return new TestSetDeleted(testSetId, true);
    }

    /**
     * 开一次检索评测（202）：立即返回 run，逐题在后台跑。
     *
     * 不带 body 就是"当前接线的全部路"（等价于给一个全默认的 CreateRunRequest）。
     */
    @PostMapping("/eval/testsets/{testset_id}/runs")
    public ResponseEntity<RunDetail> startRun(
            AuthenticatedUser caller,
            @PathVariable("testset_id") String testSetId,
            @Valid @RequestBody(required = false) CreateRunRequest request) {
        CreateRunRequest resolved = request == null ? new CreateRunRequest(null, null, null, null) : request;

        EvalRunDetail detail = evalRunService.startRun(
                caller.userId(),
                testSetId,
                resolved.topK(),
                !Boolean.FALSE.equals(resolved.queryRewrite()),
                !Boolean.FALSE.equals(resolved.rerank()),
                toPartial(resolved.fusion()));
        return accepted(runDetail(detail));
    }

    /** 开 run 的响应：202 + 详情。 */
    private static ResponseEntity<RunDetail> accepted(RunDetail body) {
        return ResponseEntity.status(HttpStatus.ACCEPTED).contentType(MediaType.APPLICATION_JSON).body(body);
    }

    /** 某评测集的历史运行（含指标，不含逐题结果），按时间倒序。 */
    @GetMapping("/eval/testsets/{testset_id}/runs")
    public RunList listRuns(AuthenticatedUser caller, @PathVariable("testset_id") String testSetId) {
        return new RunList(evalRunService.listRuns(caller.userId(), testSetId).stream()
                .map(EvalController::runView)
                .toList());
    }

    /** 重跑失败 run 的失败题：复位任务、run 回 running，后台续跑。 */
    @PostMapping("/eval/runs/{run_id}/rerun_failed")
    public RunDetail rerunFailed(AuthenticatedUser caller, @PathVariable("run_id") String runId) {
        return runDetail(evalRunService.rerunFailed(caller.userId(), runId));
    }

    /** 运行详情：状态 + 进度 + 聚合指标 + 逐题结果。 */
    @GetMapping("/eval/runs/{run_id}")
    public RunDetail getRun(AuthenticatedUser caller, @PathVariable("run_id") String runId) {
        return runDetail(evalRunService.getRun(caller.userId(), runId));
    }

    // ---- 路由内的 HTTP 契约细节（不是业务判断） ----

    /** 文件本身的后缀与大小；题目内容的规则一条不在这儿（归 jsonl 解析与 EvalService）。 */
    private static void validateUpload(MultipartFile file) {
        String filename = file.getOriginalFilename() == null ? "" : file.getOriginalFilename().strip();
        String suffix = UploadFileNames.suffixOf(filename);
        if (!ALLOWED_SUFFIXES.contains(suffix)) {
            throw new ApiError(400, "题目文件只接受 .jsonl（当前: " + (suffix.isEmpty() ? filename : suffix) + "）");
        }
        if (file.getSize() == 0) {
            throw new ApiError(400, "文件内容为空");
        }
        if (file.getSize() > MAX_UPLOAD_BYTES) {
            throw new ApiError(413, "文件过大");
        }
    }

    private static byte[] readBytes(MultipartFile file) {
        try {
            return file.getBytes();
        } catch (IOException exc) {
            throw new ApiError(500, "读取上传文件失败: " + exc.getMessage());
        }
    }

    /** {@code FusionRequest.to_partial()}：只把给出的那几项带下去（null = 没给）。 */
    private static FusionConfig toPartial(FusionRequest fusion) {
        if (fusion == null) {
            return null;
        }
        return new FusionConfig(fusion.method(), fusion.rrfK(), fusion.norm(), fusion.weights());
    }

    private static ApiError missingBody() {
        FastApiValidation.Errors errors = new FastApiValidation.Errors();
        errors.add(FastApiValidation.missing(List.of("body")));
        return new ApiError(422, errors.details());
    }

    private static TestSetView testSetView(EvalTestSet testSet) {
        return new TestSetView(
                testSet.id(), testSet.name(), testSet.itemCount(), IsoTime.format(testSet.createdAt()));
    }

    private static TestSetDetail testSetDetail(EvalTestSetDetail detail) {
        EvalTestSet testSet = detail.testSet();
        return new TestSetDetail(
                testSet.id(),
                testSet.name(),
                testSet.itemCount(),
                IsoTime.format(testSet.createdAt()),
                detail.items().stream().map(EvalController::itemView).toList());
    }

    private static ItemView itemView(EvalTestSetItem item) {
        return new ItemView(
                item.id(),
                item.query(),
                item.evidence().stream().map(EvalController::evidenceView).toList());
    }

    private static EvidenceView evidenceView(EvidenceQuote quote) {
        return new EvidenceView(quote.documentId(), quote.chunkIndex());
    }

    private static RunView runView(EvalRun run) {
        return new RunView(
                run.id(),
                run.testsetId(),
                run.status().wire(),
                run.config(),
                run.metrics(),
                run.errorMessage(),
                run.progressDone(),
                run.progressTotal(),
                IsoTime.format(run.createdAt()),
                IsoTime.format(run.finishedAt()));
    }

    private static RunDetail runDetail(EvalRunDetail detail) {
        EvalRun run = detail.run();
        return new RunDetail(
                run.id(),
                run.testsetId(),
                run.status().wire(),
                run.config(),
                run.metrics(),
                run.errorMessage(),
                run.progressDone(),
                run.progressTotal(),
                IsoTime.format(run.createdAt()),
                IsoTime.format(run.finishedAt()),
                detail.items());
    }
}
