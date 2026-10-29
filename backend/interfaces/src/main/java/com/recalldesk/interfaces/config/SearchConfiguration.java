package com.recalldesk.interfaces.config;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.recalldesk.application.search.FusionSpec;
import com.recalldesk.application.search.SearchService;
import com.recalldesk.domain.port.model.EmbeddingClient;
import com.recalldesk.domain.port.model.QueryRewriter;
import com.recalldesk.domain.port.model.Reranker;
import com.recalldesk.domain.port.persistence.ChunkIndex;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * 检索编排的接线：融合默认档是哪一档、检索服务拿到哪几路。
 */
@Configuration(proxyBeanMethods = false)
public class SearchConfiguration {

    /**
     * 融合默认档：env 管默认，run 管实验。
     *
     * 这里只回答"没给配方时怎么合"——评测 run 每个都往 config 里落完整档位，做 A/B 不靠改 env。
     * 非法值（method/norm 打错、权重为负）在 {@link FusionSpec} 构造时就抛：启动即失败，
     * 好过检索时悄悄走错路，所以这里不兜底成默认档。
     */
    @Bean
    public FusionSpec defaultFusion(
            @Value("${recalldesk.fusion.method}") String method,
            @Value("${recalldesk.fusion.rrf-k}") int rrfK,
            @Value("${recalldesk.fusion.norm}") String norm,
            @Value("${recalldesk.fusion.weights}") String weightsJson) {
        return new FusionSpec(method, rrfK, norm, weights(weightsJson));
    }

    /**
     * 检索服务：改写与重排两路默认接上。
     *
     * 每一路开不开是每次检索的档位（SearchProfile），消融实验按 run 传入；
     * 网关没配对应模型时，真正走到那一路才会显式失败，不在装配期猜。
     */
    @Bean
    public SearchService searchService(
            ChunkIndex index,
            EmbeddingClient embeddingClient,
            QueryRewriter queryRewriter,
            Reranker reranker,
            FusionSpec defaultFusion,
            @Value("${recalldesk.top-k}") int defaultTopK,
            @Value("${recalldesk.rerank.top-n}") int rerankTopN) {
        return new SearchService(
                index, embeddingClient, queryRewriter, reranker, defaultTopK, rerankTopN, defaultFusion);
    }

    /** fusion_weights 在配置里写成 JSON 串（形如 {"dense":1.0,"sparse":1.0}）。 */
    private static Map<String, Double> weights(String json) {
        try {
            return new ObjectMapper().readValue(json, new TypeReference<LinkedHashMap<String, Double>>() {});
        } catch (JsonProcessingException exc) {
            throw new IllegalStateException("recalldesk.fusion.weights 不是合法的 JSON 对象: " + json, exc);
        }
    }
}
