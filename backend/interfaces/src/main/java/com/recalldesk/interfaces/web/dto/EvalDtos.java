package com.recalldesk.interfaces.web.dto;

import com.recalldesk.application.eval.dto.EvalRunItemDto;
import com.recalldesk.domain.eval.EvalRunConfig;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import java.util.List;
import java.util.Map;

/**
 * 评测路由的出参形状与请求体形状。
 *
 * 出参：键序 = record 分量顺序；null 照旧输出（FastAPI 不裁 null）。
 * detail 接口是"元信息 + items"摊平（不是嵌套成 testset 对象），
 * 所以这里是摊平的 record 而不是嵌套。
 *
 * 形状都由「题目由用户上传、由引文判分」决定：集合上没有 status 与
 * 出题进度（导入是同步的，题目进来就是终态），证据上没有块坐标可勾（改成 quote 与它的解析落点）。
 *
 * 请求体：字段全用包装类型表达"没给"（null）——形状校验走注解，缺省落值仍在 controller。
 */
public final class EvalDtos {

    private EvalDtos() {}

    // ---- 出参 ----

    public record TestSetView(String id, String name, int itemCount, String createdAt) {}

    /** 一个金标：文档 + 块号。金标就是这块，没有原文片段、没有解析结果。 */
    public record EvidenceView(String documentId, int chunkIndex) {}

    public record ItemView(String id, String query, List<EvidenceView> evidence) {}

    /** GET /eval/testsets/{id} 与导入题后的返回：元信息摊平 + items。 */
    public record TestSetDetail(String id, String name, int itemCount, String createdAt, List<ItemView> items) {}

    public record TestSetList(List<TestSetView> testsets) {}

    public record RunView(
            String id,
            String testsetId,
            String status,
            EvalRunConfig config,
            Map<String, Object> metrics,
            String errorMessage,
            int progressDone,
            int progressTotal,
            String createdAt,
            String finishedAt) {}

    /** GET /eval/runs/{id}：元信息摊平 + items。 */
    public record RunDetail(
            String id,
            String testsetId,
            String status,
            EvalRunConfig config,
            Map<String, Object> metrics,
            String errorMessage,
            int progressDone,
            int progressTotal,
            String createdAt,
            String finishedAt,
            List<EvalRunItemDto> items) {}

    public record RunList(List<RunView> runs) {}

    public record TestSetDeleted(String testsetId, boolean deleted) {}

    // ---- 请求体 ----

    /** POST /eval/testsets：name 可空，最长 255，空或纯空白落默认名。 */
    public record CreateTestSetRequest(@Size(max = 255, message = "名称最长 255 个字符") String name) {}

    /**
     * 融合配方的请求形状：全可选，只覆盖给出的那几项。
     *
     * 不能直接用 domain 的 FusionConfig（它是 total：缺一个键就校验失败）——
     * "只改 method、其它跟默认档走"正是 overlay 的设计意图。
     */
    public record FusionRequest(
            @Pattern(regexp = "rrf|weighted", message = "fusion.method 只能是 rrf 或 weighted") String method,
            @Min(value = 1, message = "rrf_k 需在 1-1000 之间")
                    @Max(value = 1000, message = "rrf_k 需在 1-1000 之间") Integer rrfK,
            @Pattern(regexp = "minmax|zscore", message = "fusion.norm 只能是 minmax 或 zscore") String norm,
            Map<String, Double> weights) {}

    /** POST .../runs：三个开关缺省全开，不带 body 就是"当前接线的全部路"。 */
    public record CreateRunRequest(
            @Min(value = 1, message = "top_k 需在 1-50 之间")
                    @Max(value = 50, message = "top_k 需在 1-50 之间") Integer topK,
            Boolean queryRewrite,
            Boolean rerank,
            @Valid FusionRequest fusion) {}
}
