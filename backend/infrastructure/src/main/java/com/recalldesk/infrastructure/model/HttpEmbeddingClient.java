package com.recalldesk.infrastructure.model;

import com.recalldesk.domain.exception.model.ModelClientException;
import com.recalldesk.domain.port.model.EmbeddingClient;
import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * embedding 端口实现：把批量与维度校验挡在网关协议之外。
 *
 * 维度以 Java 配置为准（它必须与 DB 的 vector(N) 一致），网关报回来的维度只在启动期
 * 由 SearchConfiguration 核对一次；这里逐条校验，防止网关换了模型后静默写入错维度。
 */
@Component
public class HttpEmbeddingClient implements EmbeddingClient {

    private final ModelServiceClient client;
    private final int expectedDim;

    public HttpEmbeddingClient(
            ModelServiceClient client, @Value("${recalldesk.embedding-dim}") int expectedDim) {
        this.client = client;
        this.expectedDim = expectedDim;
    }

    @Override
    public List<double[]> embed(List<String> texts) {
        List<double[]> vectors = client.embed(texts);
        for (double[] vector : vectors) {
            if (vector.length != expectedDim) {
                throw new ModelClientException(
                        -1, "embedding 维度 " + vector.length + " 与配置 " + expectedDim + " 不一致");
            }
        }
        return vectors;
    }

    @Override
    public double[] embedOne(String text) {
        return embed(List.of(text)).getFirst();
    }
}
