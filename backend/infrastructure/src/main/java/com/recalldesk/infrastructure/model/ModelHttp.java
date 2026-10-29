package com.recalldesk.infrastructure.model;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.recalldesk.domain.exception.model.ModelClientException;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Map;

/**
 * 模型网关的一次 JSON 往返：写 body、非 2xx 抛带状态码的异常。
 *
 * 手写 HTTP 而不是引 springdoc/openai-java：网关的三个端点（/embed、/rerank、
 * /rewrite）字段差别很大，套 SDK 反而要为每个响应写适配器。
 */
final class ModelHttp {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final HttpClient client;

    ModelHttp(Duration connectTimeout) {
        this.client = HttpClient.newBuilder()
                // uvicorn（h11）不支持 h2c 升级：Java 默认的 HTTP/2 升级请求会让它丢掉 POST body
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(connectTimeout)
                .build();
    }

    JsonNode post(String url, Map<String, Object> payload, Duration timeout) {
        String body;
        try {
            body = MAPPER.writeValueAsString(payload);
        } catch (JsonProcessingException e) {
            throw new ModelClientException(-1, "请求体序列化失败: " + url, e);
        }
        HttpRequest request = HttpRequest.newBuilder(URI.create(url))
                .timeout(timeout)
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(body, StandardCharsets.UTF_8))
                .build();
        return send(request, url);
    }

    private JsonNode send(HttpRequest request, String url) {
        HttpResponse<String> response;
        try {
            response = client.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new ModelClientException(-1, "请求被中断: " + url, e);
        } catch (IOException e) {
            throw new ModelClientException(-1, "请求失败: " + url + " —— " + e.getMessage(), e);
        }
        int status = response.statusCode();
        if (status < 200 || status >= 300) {
            throw new ModelClientException(status, "HTTP " + status + " " + url + " —— " + brief(response.body()));
        }
        try {
            return MAPPER.readTree(response.body());
        } catch (JsonProcessingException e) {
            throw new ModelClientException(-1, "响应不是 JSON: " + brief(response.body()), e);
        }
    }

    /** 错误体可能是整页 HTML，截一下再进日志/异常消息。 */
    private static String brief(String body) {
        if (body == null) {
            return "";
        }
        String trimmed = body.strip();
        return trimmed.length() <= 300 ? trimmed : trimmed.substring(0, 300);
    }
}
