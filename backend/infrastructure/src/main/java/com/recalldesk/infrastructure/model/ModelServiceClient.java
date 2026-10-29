package com.recalldesk.infrastructure.model;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.recalldesk.domain.exception.model.ModelClientException;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * 模型网关的唯一入口：Java 侧只认一个 base-url，embedding / rerank / rewrite 都在网关后面。
 *
 * 这个类只说网关的协议（JSON 字段与超时），不知道 Ollama 的存在——模型名、prompt、
 * logprobs 取分都在 Python 侧。响应形状由网关负责，这里只在"条数对不上会导致错位"时报错。
 */
@Component
public class ModelServiceClient {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final ModelHttp http = new ModelHttp(Duration.ofSeconds(10));
    private final String baseUrl;
    private final Duration embedTimeout;
    private final Duration rerankTimeout;
    private final Duration rewriteTimeout;

    public ModelServiceClient(
            @Value("${recalldesk.model-service.base-url}") String baseUrl,
            @Value("${recalldesk.model-service.embed-timeout-seconds:120}") double embedTimeoutSeconds,
            @Value("${recalldesk.model-service.rerank-timeout-seconds:900}") double rerankTimeoutSeconds,
            @Value("${recalldesk.model-service.rewrite-timeout-seconds:180}") double rewriteTimeoutSeconds) {
        this.baseUrl = baseUrl.replaceAll("/+$", "");
        this.embedTimeout = seconds(embedTimeoutSeconds);
        this.rerankTimeout = seconds(rerankTimeoutSeconds);
        this.rewriteTimeout = seconds(rewriteTimeoutSeconds);
    }

    public List<double[]> embed(List<String> texts) {
        if (texts.isEmpty()) {
            return List.of();
        }
        JsonNode vectors = http.post(baseUrl + "/embed", Map.of("texts", texts), embedTimeout)
                .path("vectors");
        if (vectors.size() != texts.size()) {
            throw new ModelClientException(-1, "embed 响应条数与请求不一致");
        }
        List<double[]> result = new ArrayList<>(vectors.size());
        for (JsonNode vector : vectors) {
            double[] row = new double[vector.size()];
            for (int i = 0; i < row.length; i++) {
                row[i] = vector.get(i).asDouble();
            }
            result.add(row);
        }
        return List.copyOf(result);
    }

    public List<Double> rerank(String query, List<String> documents) {
        if (documents.isEmpty()) {
            return List.of();
        }
        RerankResponse response = read(
                http.post(baseUrl + "/rerank",
                        Map.of("query", query, "documents", documents), rerankTimeout),
                RerankResponse.class);
        if (response.scores().size() != documents.size()) {
            throw new ModelClientException(-1, "rerank 返回分数条数与候选不一致");
        }
        return response.scores();
    }

    public RewriteResponse rewrite(String query) {
        return read(
                http.post(baseUrl + "/rewrite", Map.of("query", query), rewriteTimeout),
                RewriteResponse.class);
    }

    private static <T> T read(JsonNode root, Class<T> type) {
        try {
            return MAPPER.treeToValue(root, type);
        } catch (JsonProcessingException e) {
            throw new ModelClientException(-1, "网关响应解析失败", e);
        }
    }

    private static Duration seconds(double value) {
        return Duration.ofMillis((long) (value * 1000));
    }

    /** /rerank 的响应体：字段名与网关契约一致。 */
    public record RerankResponse(List<Double> scores) {}

    /** /rewrite 的响应体：字段名与网关契约一致。 */
    public record RewriteResponse(List<String> queries, List<String> keywords) {}
}
