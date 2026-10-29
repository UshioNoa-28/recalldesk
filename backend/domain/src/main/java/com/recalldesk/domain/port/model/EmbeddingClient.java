package com.recalldesk.domain.port.model;

import java.util.List;

/**
 * 把文本变成 dense 向量的能力（实现：OpenAI 兼容 /v1/embeddings，含 Ollama 的那层兼容接口）。
 *
 * 同步阻塞——Java 侧整条链都是阻塞的（JDBC + 虚拟线程），不返回 CompletableFuture。
 */
public interface EmbeddingClient {

    /** 批量生成向量，返回顺序与输入一致。 */
    List<double[]> embed(List<String> texts);

    /** 单条文本生成向量。 */
    double[] embedOne(String text);
}
