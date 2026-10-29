package com.recalldesk.infrastructure.model;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 进程内假模型端点：把请求体收下来给断言看，按脚本回响应。
 *
 * 客户端的"发出去长什么样"就是它对外的承诺，这部分没有现成金标准可抄，
 * 只能钉在测试里；而它确实会打网络，所以用 JDK 自带的 HttpServer 在本地端口上跑，
 * 不进 CI 也不依赖本机有没有 Ollama。
 */
final class StubModelServer implements AutoCloseable {

    /** 一次收到的请求：路径、Authorization 头、解析后的 JSON 体。 */
    record Request(String path, String authorization, JsonNode body) {}

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final HttpServer server;
    private final List<Request> requests = new ArrayList<>();
    private final Map<String, List<String>> responsesByPath = new LinkedHashMap<>();
    private final Map<String, Integer> cursorByPath = new LinkedHashMap<>();
    private volatile int failStatus;

    StubModelServer() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/", this::handle);
        server.start();
    }

    String baseUrl() {
        return "http://127.0.0.1:" + server.getAddress().getPort();
    }

    /** 同一路径可以排多条响应，用完了就重复最后一条。 */
    void respondWith(String path, String... jsonBodies) {
        responsesByPath.put(path, List.of(jsonBodies));
    }

    /** 下一条请求回这个状态码（用来演 Ollama 的 5xx 冷加载）。 */
    void failNextWith(int status) {
        this.failStatus = status;
    }

    List<Request> requests() {
        return List.copyOf(requests);
    }

    Request lastRequest() {
        return requests.get(requests.size() - 1);
    }

    private void handle(HttpExchange exchange) throws IOException {
        // 模拟 uvicorn：h11 不认识 h2c 升级，收到 Upgrade 头会丢 body。客户端必须固定 HTTP/1.1
        if (exchange.getRequestHeaders().containsKey("Upgrade")) {
            byte[] out = "{\"detail\":\"h2c upgrade unsupported\"}".getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(400, out.length);
            exchange.getResponseBody().write(out);
            exchange.close();
            return;
        }
        String path = exchange.getRequestURI().getPath();
        String raw = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
        requests.add(new Request(path, exchange.getRequestHeaders().getFirst("Authorization"),
                raw.isEmpty() ? MAPPER.createObjectNode() : MAPPER.readTree(raw)));
        List<String> scripted = responsesByPath.get(path);
        int index = Math.min(cursorByPath.merge(path, 1, Integer::sum) - 1, scripted == null ? 0 : scripted.size() - 1);
        int status = failStatus;
        failStatus = 0;
        String body = scripted == null ? "{}" : scripted.get(index);
        byte[] out = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().add("Content-Type", "application/json");
        exchange.sendResponseHeaders(status == 0 ? 200 : status, out.length);
        exchange.getResponseBody().write(out);
        exchange.close();
    }

    @Override
    public void close() {
        server.stop(0);
    }
}
