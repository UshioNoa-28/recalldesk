package com.recalldesk.application.search;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.groups.Tuple.tuple;

import com.recalldesk.domain.port.persistence.ChunkIndex;
import com.recalldesk.domain.port.model.EmbeddingClient;
import com.recalldesk.domain.port.model.QueryRewriter;
import com.recalldesk.domain.port.model.Reranker;
import com.recalldesk.domain.retrieval.ChannelTrace;
import com.recalldesk.domain.retrieval.ChunkHit;
import com.recalldesk.domain.retrieval.ChunkRecord;
import com.recalldesk.domain.retrieval.QueryRewrite;
import com.recalldesk.application.search.FusionSpec;
import com.recalldesk.application.search.dto.SearchOutcome;
import com.recalldesk.application.search.dto.SearchProfile;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * SearchService 单元测试（假仓储 / 假 embedding / 假重排，纯逻辑，离线跑）。
 *
 * 用例与 tests/test_search_service.py 的 SearchServiceTests / SearchOutcomeTests 一一对应。
 */
class SearchServiceTest {

    private static final Map<String, Double> EQUAL = Map.of("dense", 1.0, "sparse", 1.0);
    /** 检索视野：归属由调用方（已验签的身份）给出，两路 SQL 都带它做过滤。 */
    private static final String ALICE = "user-alice";

    private static ChunkHit hit(int chunkIndex, double score) {
        return new ChunkHit("doc-1", "a.txt", chunkIndex, 3, "内容", score);
    }

    private static FusionSpec rrf() {
        return new FusionSpec("rrf", 60, "minmax", EQUAL);
    }

    private static FusionSpec weighted() {
        return new FusionSpec("weighted", 60, "minmax", EQUAL);
    }

    private static List<Integer> indexes(List<ChunkHit> hits) {
        return hits.stream().map(ChunkHit::chunkIndex).toList();
    }

    /** 两路名次集合一样，但分差形状不同：weighted 会记住 dense 里的那次领先。 */
    private static FakeChunkIndex unevenChannels() {
        return new FakeChunkIndex(
                List.of(hit(0, 0.95), hit(1, 0.30), hit(2, 0.29)),
                List.of(hit(1, 20.0), hit(0, 19.9), hit(2, 0.1)));
    }

    @Test
    @DisplayName("两路召回融合后按名次排，且各路都拿到同一份查询文本")
    void searchFusesTwoChannels() {
        FakeChunkIndex index = new FakeChunkIndex(List.of(hit(0, 0.9), hit(1, 0.5)), List.of(hit(1, 9.0), hit(0, 2.0)));
        SearchService service = new SearchService(index, new FakeEmbeddingClient(), null, null, 3, 20, rrf());

        List<ChunkHit> results = service.search("香蕉 营养", null, null, ALICE).hits();

        assertThat(indexes(results)).startsWith(0, 1);
        // 两路各拿一个第一与一个第二：1/60 + 1/61，融合分不再截断
        assertThat(results.getFirst())
                .extracting(ChunkHit::documentId, ChunkHit::documentName, ChunkHit::chunkIndex,
                        ChunkHit::chunkCount, ChunkHit::text, ChunkHit::score)
                .containsExactly("doc-1", "a.txt", 0, 3, "内容", 1.0 / 60 + 1.0 / 61);
        // 两路都拿到了同一个查询向量与原文（假 embedding 把向量填成文本长度）
        assertThat(index.lastDenseVector).containsExactly(5.0, 5.0, 5.0, 5.0);
        assertThat(index.sparseQueries).containsExactly("香蕉 营养");
        // 归属下推进每一路：只筛一路会让另一路的命中带着别人的文档
        assertThat(index.searchedFor).containsExactly(ALICE, ALICE);
    }

    @Test
    @DisplayName("每路耗时各记各的：慢的那路不会把等待算到快的路头上")
    void eachChannelCarriesItsOwnLatency() {
        FakeChunkIndex index = new FakeChunkIndex(List.of(hit(0, 0.9)), List.of(hit(1, 9.0)));
        index.denseDelayMs = 25;
        SearchService service = new SearchService(index, new FakeEmbeddingClient(), null, null, 3, 20, rrf());

        SearchOutcome outcome = service.search("香蕉 营养", null, null, ALICE);

        assertThat(outcome.channels()).hasSize(2);
        assertThat(outcome.channels().get(0).kind()).isEqualTo("dense_original");
        assertThat(outcome.channels().get(1).kind()).isEqualTo("sparse");
        // 下限是硬事实（睡满 25ms 才返回）；上限只断「并发跑的另一路不该被算进来的」
        assertThat(outcome.channels().get(0).tookMs()).isGreaterThanOrEqualTo(25);
        assertThat(outcome.channels().get(1).tookMs()).isLessThan(25);
    }

    @Test
    @DisplayName("档位里的 fusion 决定用哪种融合算法")
    void searchProfilePicksTheFusionAlgorithm() {
        SearchService service = new SearchService(
                unevenChannels(), new FakeEmbeddingClient(), null, null, 3, 20, rrf());

        List<ChunkHit> rrfHits = service.search("查询", null, new SearchProfile(false, true, null), ALICE).hits();
        List<ChunkHit> weightedHits =
                service.search("查询", null, new SearchProfile(false, true, weighted()), ALICE).hits();

        assertThat(rrfHits.get(0).score()).isEqualTo(rrfHits.get(1).score());
        assertThat(weightedHits.get(0).score()).isGreaterThan(weightedHits.get(1).score());
    }

    @Test
    @DisplayName("档位没带 fusion 时走装配默认（交互式 /search 就靠这条路换默认档）")
    void assemblyDefaultAppliesWhenProfileGivesNone() {
        SearchService service = new SearchService(
                unevenChannels(), new FakeEmbeddingClient(), null, null, 3, 20, weighted());

        List<ChunkHit> results = service.search("查询", null, new SearchProfile(false, true, null), ALICE).hits();

        assertThat(results.get(0).score()).isGreaterThan(results.get(1).score());
    }

    @Test
    @DisplayName("没给 top_k 时用装配默认值")
    void searchUsesDefaultTopK() {
        FakeChunkIndex index = new FakeChunkIndex(List.of(), List.of());
        SearchService service = new SearchService(index, new FakeEmbeddingClient(), null, null, 3, 20, rrf());

        service.search("查询", null, null, ALICE);

        assertThat(index.topKs).containsExactly(3, 3);
    }

    @Test
    @DisplayName("接了重排：融合前按 rerank_top_n 取宽候选，重排后再截回 top_k")
    void withRerankerFetchesMoreCandidatesThenTruncates() {
        FakeChunkIndex index = new FakeChunkIndex(
                List.of(hit(0, 1.0), hit(1, 0.9), hit(2, 0.8), hit(3, 0.7), hit(4, 0.6)), List.of());
        FakeReranker reranker = new FakeReranker();
        SearchService service = new SearchService(index, new FakeEmbeddingClient(), null, reranker, 3, 5, rrf());

        List<ChunkHit> results = service.search("查询", null, null, ALICE).hits();

        assertThat(reranker.called).isTrue();
        assertThat(index.topKs).containsExactly(5, 5);
        assertThat(reranker.topK).isEqualTo(3);
        assertThat(results).hasSize(3);
    }

    @Test
    @DisplayName("档位关掉改写：接线在也不走，回到最朴素的两路")
    void profileOffRewriteSkipsVariants() {
        FakeRewriter rewriter = new FakeRewriter(new QueryRewrite(List.of("变体一"), List.of("关键词", "豆腐")));
        FakeChunkIndex index = new FakeChunkIndex(List.of(hit(0, 0.9)), List.of());
        SearchService service = new SearchService(index, new FakeEmbeddingClient(), rewriter, null, 3, 20, rrf());

        SearchOutcome outcome = service.search("原查询", null, new SearchProfile(false, true, null), ALICE);

        assertThat(rewriter.calls).isEmpty();
        assertThat(outcome.channels())
                .extracting(ChannelTrace::kind, ChannelTrace::text)
                .containsExactly(tuple("dense_original", "原查询"), tuple("sparse", "原查询"));
    }

    @Test
    @DisplayName("关重排连候选宽度一起回到 top_k：rerank_top_n 只为重排而存在")
    void profileOffRerankKeepsFusionOutputPlain() {
        FakeChunkIndex index = new FakeChunkIndex(
                List.of(hit(0, 1.0), hit(1, 0.9), hit(2, 0.8), hit(3, 0.7), hit(4, 0.6)), List.of());
        FakeReranker reranker = new FakeReranker();
        SearchService service = new SearchService(index, new FakeEmbeddingClient(), null, reranker, 3, 5, rrf());

        List<ChunkHit> results = service.search("查询", null, new SearchProfile(true, false, null), ALICE).hits();

        assertThat(reranker.called).isFalse();
        assertThat(index.topKs).containsExactly(3, 3);
        assertThat(results).hasSize(3);
    }

    @Test
    @DisplayName("档位是意图、接线才是上限：全开但没接的路静默缺路，不报错")
    void profileIsIntentWiringIsTheCeiling() {
        FakeChunkIndex index = new FakeChunkIndex(List.of(hit(0, 0.9)), List.of());
        SearchService service = new SearchService(index, new FakeEmbeddingClient(), null, null, 3, 20, rrf());

        SearchOutcome outcome = service.search("查询", null, SearchProfile.defaults(), ALICE);

        assertThat(outcome.channels()).extracting(ChannelTrace::kind).containsExactly("dense_original", "sparse");
    }

    @Test
    @DisplayName("节点评估的轨迹出口：每一路都留痕，命中按本路分数降序定格")
    void tracesEveryRouteWithQueryTextsAndSortedHits() {
        FakeRewriter rewriter = new FakeRewriter(new QueryRewrite(List.of("变体一", "变体二"), List.of("关键词", "豆腐")));
        // 故意乱序返回：轨迹必须按本路分数降序存，名次以排序后为准
        FakeChunkIndex index = new FakeChunkIndex(List.of(hit(1, 0.5), hit(0, 0.9)), List.of(hit(2, 7.0)));
        SearchService service = new SearchService(index, new FakeEmbeddingClient(), rewriter, null, 3, 20, rrf());

        SearchOutcome outcome = service.search("原查询", null, null, ALICE);

        assertThat(outcome.channels())
                .extracting(ChannelTrace::kind, ChannelTrace::text)
                .containsExactly(
                        tuple("dense_original", "原查询"),
                        tuple("dense_variant", "变体一"),
                        tuple("dense_variant", "变体二"),
                        tuple("sparse", "关键词 豆腐"));
        assertThat(indexes(outcome.channels().getFirst().hits())).containsExactly(0, 1);
        assertThat(outcome.hits()).hasSize(3); // 融合结果照旧
    }

    @Test
    @DisplayName("单一出口：对外 hits + 逐路 channels 一次拿全")
    void searchReturnsTheFullOutcome() {
        FakeChunkIndex index = new FakeChunkIndex(List.of(hit(0, 0.9)), List.of());
        SearchService service = new SearchService(index, new FakeEmbeddingClient(), null, null, 3, 20, rrf());

        SearchOutcome outcome = service.search("查询", null, null, ALICE);

        assertThat(indexes(outcome.hits())).containsExactly(0);
        assertThat(outcome.channels()).extracting(ChannelTrace::kind).containsExactly("dense_original", "sparse");
    }

    /** 记录调用的假仓储：两路各返回预设命中，别的都不支持（本服务只会走这两路）。 */
    private static void sleep(long millis) {
        if (millis <= 0) {
            return;
        }
        try {
            Thread.sleep(millis);
        } catch (InterruptedException exc) {
            Thread.currentThread().interrupt();
        }
    }

    private static class FakeChunkIndex implements ChunkIndex {

        final List<ChunkHit> denseHits;
        final List<ChunkHit> sparseHits;
        final List<String> sparseQueries = new ArrayList<>();
        final List<Integer> topKs = new ArrayList<>();
        final List<String> searchedFor = new ArrayList<>();
        /** 让某一路慢下来：耗时是在本路线程上掐的表，不是从 join 那侧看的（见下面那条用例）。 */
        long denseDelayMs;
        long sparseDelayMs;
        double[] lastDenseVector;

        FakeChunkIndex(List<ChunkHit> denseHits, List<ChunkHit> sparseHits) {
            this.denseHits = denseHits;
            this.sparseHits = sparseHits;
        }

        @Override
        public List<ChunkHit> searchByDense(double[] denseVector, int topK, String userId) {
            sleep(denseDelayMs);
            lastDenseVector = denseVector;
            topKs.add(topK);
            searchedFor.add(userId);
            return denseHits;
        }

        @Override
        public List<ChunkHit> searchBySparse(String queryText, int topK, String userId) {
            sleep(sparseDelayMs);
            sparseQueries.add(queryText);
            topKs.add(topK);
            searchedFor.add(userId);
            return sparseHits;
        }

        @Override
        public void insertChunks(
                String documentId, String userId, String documentName, List<String> chunks, List<double[]> vectors) {
            throw new UnsupportedOperationException();
        }

        @Override
        public List<ChunkRecord> getDocumentChunks(String documentId) {
            throw new UnsupportedOperationException();
        }

        @Override
        public Optional<ChunkRecord> getChunk(String documentId, int chunkIndex) {
            throw new UnsupportedOperationException();
        }

        @Override
        public void deleteDocument(String documentId) {
            throw new UnsupportedOperationException();
        }
    }

    /** 假 embedding：把文本长度铺满向量，查询向量可预测。 */
    private static class FakeEmbeddingClient implements EmbeddingClient {

        private static final int DIM = 4;

        @Override
        public List<double[]> embed(List<String> texts) {
            return texts.stream().map(this::embedOne).toList();
        }

        @Override
        public double[] embedOne(String text) {
            double[] vector = new double[DIM];
            Arrays.fill(vector, text.length());
            return vector;
        }
    }

    /** 记录调用并把候选原样吐回的替身。 */
    private static class FakeReranker implements Reranker {

        boolean called;
        String query;
        List<ChunkHit> candidates = List.of();
        Integer topK;

        @Override
        public List<ChunkHit> rerank(String query, List<ChunkHit> candidates, int topK) {
            called = true;
            this.query = query;
            this.candidates = candidates;
            this.topK = topK;
            return candidates.subList(0, Math.min(topK, candidates.size()));
        }
    }

    /** 改写替身：记住被问过哪些查询，恒定返回同一个产出。 */
    private static class FakeRewriter implements QueryRewriter {

        final List<String> calls = new ArrayList<>();
        private final QueryRewrite value;

        FakeRewriter(QueryRewrite value) {
            this.value = value;
        }

        @Override
        public QueryRewrite rewrite(String query) {
            calls.add(query);
            return value;
        }
    }
}
