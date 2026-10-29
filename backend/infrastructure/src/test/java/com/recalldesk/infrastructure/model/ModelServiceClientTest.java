package com.recalldesk.infrastructure.model;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.recalldesk.domain.exception.model.ModelClientException;
import com.recalldesk.domain.retrieval.ChunkHit;
import com.recalldesk.domain.retrieval.QueryRewrite;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 模型网关客户端的线上形状（离线，打的是进程内假端点）。
 *
 * 钉的是"发出去的 JSON 长什么样、回来的 JSON 怎么读"：字段名一个字母都不能错，
 * 而对端是不可控的外部服务——出问题时能说清"我们发的是什么"的只有这些断言。
 */
class ModelServiceClientTest {

    private static ModelServiceClient client(StubModelServer stub) {
        return new ModelServiceClient(stub.baseUrl() + "/", 30, 30, 30);
    }

    private static ChunkHit hit(int chunkIndex, String text, double score) {
        return new ChunkHit("doc-1", "a.txt", chunkIndex, 3, text, score);
    }

    @Test
    @DisplayName("embedding：请求带 texts，响应按序读成向量")
    void embeddingSendsTexts() throws Exception {
        try (StubModelServer stub = new StubModelServer()) {
            stub.respondWith("/embed", "{\"vectors\":[[0.1,0.15],[0.2,0.3]],\"dim\":2}");
            HttpEmbeddingClient client = new HttpEmbeddingClient(client(stub), 2);

            List<double[]> vectors = client.embed(List.of("甲", "乙"));

            assertThat(vectors).hasSize(2);
            assertThat(vectors.getFirst()).containsExactly(0.1, 0.15);
            assertThat(vectors.get(1)).containsExactly(0.2, 0.3);

            StubModelServer.Request request = stub.lastRequest();
            assertThat(request.path()).isEqualTo("/embed");
            assertThat(request.body().path("texts")).hasSize(2);
            assertThat(request.body().path("texts").get(0).asText()).isEqualTo("甲");
        }
    }

    @Test
    @DisplayName("embedding 维度与 Java 配置不一致：显式失败，不静默写入")
    void embeddingDimensionMismatchRejected() throws Exception {
        try (StubModelServer stub = new StubModelServer()) {
            stub.respondWith("/embed", "{\"vectors\":[[0.1,0.2]],\"dim\":2}");
            HttpEmbeddingClient client = new HttpEmbeddingClient(client(stub), 1024);

            assertThatThrownBy(() -> client.embedOne("甲"))
                    .isInstanceOf(ModelClientException.class)
                    .hasMessageContaining("维度 2 与配置 1024 不一致");
        }
    }

    @Test
    @DisplayName("rerank：分数按候选顺序绑回，稳定排序后截 top_k")
    void rerankBindsScoresAndSorts() throws Exception {
        try (StubModelServer stub = new StubModelServer()) {
            stub.respondWith("/rerank", "{\"scores\":[0.4,0.9]}");
            HttpReranker reranker = new HttpReranker(client(stub));

            List<ChunkHit> reranked = reranker.rerank(
                    " 年假几天 ", List.of(hit(0, "年假为 98 天", 0.1), hit(1, "年假 5 天", 0.2)), 1);

            assertThat(reranked).singleElement().satisfies(hit -> {
                assertThat(hit.chunkIndex()).isEqualTo(1);
                assertThat(hit.score()).isEqualTo(0.9);
                assertThat(hit.text()).isEqualTo("年假 5 天");
            });

            StubModelServer.Request request = stub.lastRequest();
            assertThat(request.path()).isEqualTo("/rerank");
            assertThat(request.body().path("query").asText()).isEqualTo(" 年假几天 ");
            assertThat(request.body().path("documents")).hasSize(2);
        }
    }

    @Test
    @DisplayName("rerank 同分保持融合后的先后：并列名次不该变成第二次掷骰子")
    void rerankTiesKeepInputOrder() throws Exception {
        try (StubModelServer stub = new StubModelServer()) {
            stub.respondWith("/rerank", "{\"scores\":[0.5,0.5]}");
            HttpReranker reranker = new HttpReranker(client(stub));

            List<ChunkHit> reranked = reranker.rerank(
                    "q", List.of(hit(0, "甲", 0.1), hit(1, "乙", 0.2)), 2);

            assertThat(reranked).extracting(ChunkHit::chunkIndex).containsExactly(0, 1);
        }
    }

    @Test
    @DisplayName("rewrite：只做 JSON → 值对象转换")
    void rewriteMapsResponse() throws Exception {
        try (StubModelServer stub = new StubModelServer()) {
            stub.respondWith("/rewrite",
                    "{\"queries\":[\"q1\",\"q2\"],\"keywords\":[\"apple\",\"vitamin\"]}");
            HttpQueryRewriter rewriter = new HttpQueryRewriter(client(stub));

            QueryRewrite rewrite = rewriter.rewrite("苹果维C");

            assertThat(rewrite.queries()).containsExactly("q1", "q2");
            assertThat(rewrite.keywords()).containsExactly("apple", "vitamin");
            assertThat(rewrite.sparseText()).isEqualTo("apple vitamin");
            assertThat(stub.lastRequest().path()).isEqualTo("/rewrite");
        }
    }

    @Test
    @DisplayName("网关非 2xx 映射成带状态码的 ModelClientException")
    void non2xxMapsToModelClientException() throws Exception {
        try (StubModelServer stub = new StubModelServer()) {
            stub.failNextWith(503);

            assertThatThrownBy(() -> client(stub).embed(List.of("甲")))
                    .isInstanceOfSatisfying(ModelClientException.class,
                            exc -> assertThat(exc.statusCode()).isEqualTo(503));
        }
    }
}
