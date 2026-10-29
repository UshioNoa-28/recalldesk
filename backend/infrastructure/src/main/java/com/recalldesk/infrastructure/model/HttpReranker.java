package com.recalldesk.infrastructure.model;

import com.recalldesk.domain.port.model.Reranker;
import com.recalldesk.domain.retrieval.ChunkHit;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import org.springframework.stereotype.Component;

/**
 * rerank 端口实现：网关回分数，这里只负责把分数绑回候选并稳定排序。
 *
 * 分数只用于排序：P(yes) 的量纲与 RRF 分不同，不跨体系比较。
 */
@Component
public class HttpReranker implements Reranker {

    private final ModelServiceClient client;

    public HttpReranker(ModelServiceClient client) {
        this.client = client;
    }

    @Override
    public List<ChunkHit> rerank(String query, List<ChunkHit> candidates, int topK) {
        if (candidates.isEmpty()) {
            return List.of();
        }
        List<String> documents = new ArrayList<>(candidates.size());
        for (ChunkHit candidate : candidates) {
            documents.add(candidate.text() == null ? "" : candidate.text());
        }
        List<Double> scores = client.rerank(query, documents);

        List<Scored> scored = new ArrayList<>(candidates.size());
        for (int i = 0; i < candidates.size(); i++) {
            scored.add(new Scored(candidates.get(i), scores.get(i)));
        }
        // 稳定排序：同分保持融合后的先后，重排不许把并列名次变成第二次掷骰子
        scored.sort(Comparator.comparingDouble(Scored::score).reversed());

        int limit = Math.min(topK, scored.size());
        List<ChunkHit> reranked = new ArrayList<>(limit);
        for (int i = 0; i < limit; i++) {
            ChunkHit hit = scored.get(i).hit();
            reranked.add(new ChunkHit(hit.documentId(), hit.documentName(), hit.chunkIndex(),
                    hit.chunkCount(), hit.text(), scored.get(i).score()));
        }
        return List.copyOf(reranked);
    }

    /** 候选与它的重排分；排序期间两者必须绑在一起走。 */
    private record Scored(ChunkHit hit, double score) {}
}
