package com.recalldesk.application.search;

import com.recalldesk.domain.port.model.EmbeddingClient;
import com.recalldesk.domain.port.model.QueryRewriter;
import com.recalldesk.domain.port.model.Reranker;
import com.recalldesk.domain.port.persistence.ChunkIndex;
import com.recalldesk.domain.retrieval.ChannelTrace;
import com.recalldesk.domain.retrieval.ChunkHit;
import com.recalldesk.domain.retrieval.QueryRewrite;
import com.recalldesk.application.search.FusionSpec;
import com.recalldesk.application.search.dto.SearchOutcome;
import com.recalldesk.application.search.dto.SearchProfile;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * 检索编排：多路召回 → 按配方融合 →（可选）LLM 重排。
 *
 * 多路形态：
 * - 改写未接入：dense 原查询 1 路 + sparse 1 路
 * - 改写接入：dense = 原查询 + N 个改写变体（保底原查询），sparse 仍是单路关键词
 *
 * 各路并行是虚拟线程 each-per-task：一次检索要打 1+N 次 embedding 加同样多次查询，
 * 串行就是把这些往返时间全加起来。每路自己 embed→search 一条龙
 * gather，结果一样，少一次同步点）。
 *
 * 各路怎么合不在本类：融合是纯计算，住在 {@link Fusion}。本服务只管"有几路、
 * 各路的轨迹、合完要不要重排"。
 */
public class SearchService {

    private static final Logger log = LoggerFactory.getLogger(SearchService.class);

    private final ChunkIndex index;
    private final EmbeddingClient embeddingClient;
    /** 可空：模型侧没接改写路时为空（Java 没有 None，这里用 null 表达"缺路"）。 */
    private final QueryRewriter rewriter;
    private final Reranker reranker;
    private final int rerankTopN;
    private final int defaultTopK;
    /** 交互式查询没人传档位时的融合算法；评测 run 一律显式带 spec。 */
    private final FusionSpec defaultFusion;

    public SearchService(
            ChunkIndex index,
            EmbeddingClient embeddingClient,
            QueryRewriter rewriter,
            Reranker reranker,
            int defaultTopK,
            int rerankTopN,
            FusionSpec defaultFusion) {
        this.index = index;
        this.embeddingClient = embeddingClient;
        this.rewriter = rewriter;
        this.reranker = reranker;
        this.defaultTopK = defaultTopK;
        this.rerankTopN = rerankTopN;
        this.defaultFusion = defaultFusion;
    }

    /**
     * @param profile 本次的档位（哪几路各开不开 + 怎么合），缺省全开、融合走装配默认；
     *     与装配接线取与——某路没接上（LLM/Ollama 未配置）时无论档位怎么走都是缺路。
     *     消融实验由评测 run 按 config 构造档位，交互式查询一律默认。
     * @param userId 归属过滤，每次调用必填：召回是「只在这个用户的块里找」，没有全库档。
     */
    public SearchOutcome search(String query, Integer topK, SearchProfile profile, String userId) {
        SearchProfile activeProfile = profile == null ? SearchProfile.defaults() : profile;
        // 0 与缺省同义（前端把 0 当作"没填"传过来）
        int effectiveTopK = topK == null || topK == 0 ? defaultTopK : topK;
        // 档位 ∧ 接线：这次真正会走的路（没接上的路怎么都不会走）
        QueryRewriter activeRewriter = activeProfile.rewrite() ? rewriter : null;
        Reranker activeReranker = activeProfile.rerank() ? reranker : null;
        // 重排生效时才先取更多候选（rerankTopN），重排后再截回 top_k
        int candidateLimit = activeReranker == null ? effectiveTopK : Math.max(effectiveTopK, rerankTopN);

        List<String> denseTexts = new ArrayList<>();
        denseTexts.add(query);
        List<String> sparseTexts = new ArrayList<>();
        sparseTexts.add(query);
        if (activeRewriter != null) {
            QueryRewrite rewrite = activeRewriter.rewrite(query);
            denseTexts.addAll(rewrite.queries()); // 原查询保底 + 变体
            sparseTexts = List.of(rewrite.sparseText()); // 稀疏仍是单路关键词
        }

        // 轨迹是融合的唯一输入：名次约定由 ChannelTrace.of 定格（本路 score 降序）
        long startedAt = System.nanoTime();
        List<ChannelRecall> results = recall(denseTexts, sparseTexts, candidateLimit, userId);
        List<ChannelTrace> traces = new ArrayList<>(results.size());
        for (int i = 0; i < denseTexts.size(); i++) {
            traces.add(ChannelTrace.of(
                    i == 0 ? "dense_original" : "dense_variant", denseTexts.get(i),
                    results.get(i).hits(), results.get(i).tookMs()));
        }
        for (int i = 0; i < sparseTexts.size(); i++) {
            ChannelRecall recall = results.get(denseTexts.size() + i);
            traces.add(ChannelTrace.of("sparse", sparseTexts.get(i), recall.hits(), recall.tookMs()));
        }

        // 一行说清这次检索花在哪：各路是并发的，所以 total 不等于各路之和（差值就是
        // 融合与重排）——消融「关掉改写路能省多少」要的正是这两个数
        log.info(
                "检索耗时: total={}ms candidates={} recalled={} channels={}",
                (System.nanoTime() - startedAt) / 1_000_000,
                candidateLimit,
                traces.stream().mapToInt(trace -> trace.hits().size()).sum(),
                channelTimings(traces));

        List<ChunkHit> fused = Fusion.fuse(
                traces, activeProfile.fusion() == null ? defaultFusion : activeProfile.fusion(), candidateLimit);
        if (activeReranker != null) {
            return new SearchOutcome(activeReranker.rerank(query, fused, effectiveTopK), traces);
        }
        return new SearchOutcome(fused.subList(0, Math.min(effectiveTopK, fused.size())), traces);
    }

    /** 每路一个虚拟线程：embed 完立刻查，路之间并发。 */
    private List<ChannelRecall> recall(
            List<String> denseTexts, List<String> sparseTexts, int candidateLimit, String userId) {
        try (ExecutorService executor = Executors.newVirtualThreadPerTaskExecutor()) {
            List<Future<ChannelRecall>> futures = new ArrayList<>();
            for (String text : denseTexts) {
                futures.add(executor.submit(timed(() ->
                        index.searchByDense(embeddingClient.embedOne(text), candidateLimit, userId))));
            }
            for (String text : sparseTexts) {
                futures.add(executor.submit(timed(() -> index.searchBySparse(text, candidateLimit, userId))));
            }
            List<ChannelRecall> results = new ArrayList<>(futures.size());
            for (Future<ChannelRecall> future : futures) {
                results.add(join(future));
            }
            return results;
        }
    }

    /**
     * 在本路自己的线程上掐表：从 join 那侧量会串进别的路的等待时间，
     * 「dense 变体路慢」就变成「哪条都慢」。
     */
    private static Callable<ChannelRecall> timed(Callable<List<ChunkHit>> work) {
        return () -> {
            long began = System.nanoTime();
            List<ChunkHit> hits = work.call();
            return new ChannelRecall(hits, (System.nanoTime() - began) / 1_000_000);
        };
    }

    /** kind -> 毫秒（同名多路取最后一次；dense_variant 的变体序号在日志里没意义）。 */
    private static Map<String, Long> channelTimings(List<ChannelTrace> traces) {
        Map<String, Long> timings = new LinkedHashMap<>();
        for (ChannelTrace trace : traces) {
            timings.put(trace.kind(), trace.tookMs());
        }
        return timings;
    }

    /** 一路的召回结果与该路耗时。 */
    private record ChannelRecall(List<ChunkHit> hits, long tookMs) {}

    /** gather 的语义：一路失败就是整次检索失败，不静默按空路合。 */
    private static ChannelRecall join(Future<ChannelRecall> future) {
        try {
            return future.get();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("检索被中断", e);
        } catch (ExecutionException e) {
            if (e.getCause() instanceof RuntimeException runtimeException) {
                throw runtimeException;
            }
            throw new IllegalStateException("检索失败", e.getCause());
        }
    }
}
