package com.recalldesk.interfaces.config;

import com.recalldesk.application.document.IndexingService;
import com.recalldesk.application.search.SearchService;
import com.recalldesk.application.worker.DocumentTaskConsumer;
import com.recalldesk.application.worker.DocumentTaskPublisher;
import com.recalldesk.application.worker.EvalRunConsumer;
import com.recalldesk.application.worker.EvalRunTaskPublisher;
import com.recalldesk.domain.port.persistence.DocumentFileStorage;
import com.recalldesk.domain.port.persistence.DocumentRepository;
import com.recalldesk.domain.port.persistence.DocumentTaskRepository;
import com.recalldesk.domain.port.persistence.EvalRepository;
import com.recalldesk.domain.port.persistence.EvalRunRepository;
import com.recalldesk.domain.port.persistence.EvalRunTaskRepository;
import com.recalldesk.domain.port.queue.DocumentTaskQueue;
import com.recalldesk.domain.port.queue.EvalRunTaskQueue;
import com.recalldesk.domain.port.ops.UnitOfWork;
import com.recalldesk.domain.task.RedisBackend;
import com.recalldesk.domain.task.TaskPolicy;
import com.recalldesk.infrastructure.redis.RedisDocumentTaskQueue;
import com.recalldesk.infrastructure.redis.RedisEvalRunTaskQueue;
import com.recalldesk.interfaces.worker.WorkerRunner;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.core.StringRedisTemplate;

/**
 * 四个 worker 的装配（组合根）：一个进程只领一类角色。
 *
 * 角色由 {@code recalldesk.worker.role} 选（document-publisher / document-consumer /
 * eval-run-publisher / eval-run-consumer），对应两条异步链路：索引与逐题评测。
 * 题目改为用户上传之后，出题那条链路（第三个 publisher/consumer 对）就没有存在理由了。
 *
 * 队列与两条策略（stream/group/节奏/重试预算）在这里从 application.yml 读成值对象后注入，
 * 下游拿到的是明确类型，不再各自读配置的同名旋钮——组合根把配置切片成值对象，
 * 切片成 frozen dataclass"同一条纪律。
 */
@Configuration(proxyBeanMethods = false)
public class WorkerConfiguration {

    // ---- 队列公共参数与两条链路策略 ----

    @Bean
    public RedisBackend redisBackend(
            @Value("${recalldesk.streams.maxlen}") int maxlen,
            @Value("${recalldesk.streams.claim-min-idle-ms}") int claimMinIdleMs) {
        return new RedisBackend(maxlen, claimMinIdleMs);
    }

    @Bean
    public TaskPolicy documentTaskPolicy(
            @Value("${recalldesk.streams.document.stream}") String stream,
            @Value("${recalldesk.streams.document.consumer-group}") String consumerGroup,
            @Value("${recalldesk.streams.document.publish-interval-seconds}") double publishIntervalSeconds,
            @Value("${recalldesk.streams.document.publish-batch-size}") int publishBatchSize,
            @Value("${recalldesk.streams.document.max-attempts}") int maxAttempts,
            @Value("${recalldesk.streams.document.retry-backoff-seconds}") double retryBackoffSeconds) {
        return new TaskPolicy(
                stream, consumerGroup, publishIntervalSeconds, publishBatchSize, maxAttempts, retryBackoffSeconds);
    }

    @Bean
    public TaskPolicy evalRunTaskPolicy(
            @Value("${recalldesk.streams.eval-run.stream}") String stream,
            @Value("${recalldesk.streams.eval-run.consumer-group}") String consumerGroup,
            @Value("${recalldesk.streams.eval-run.publish-interval-seconds}") double publishIntervalSeconds,
            @Value("${recalldesk.streams.eval-run.publish-batch-size}") int publishBatchSize,
            @Value("${recalldesk.streams.eval-run.max-attempts}") int maxAttempts,
            @Value("${recalldesk.streams.eval-run.retry-backoff-seconds}") double retryBackoffSeconds) {
        return new TaskPolicy(
                stream, consumerGroup, publishIntervalSeconds, publishBatchSize, maxAttempts, retryBackoffSeconds);
    }

    // ---- 两条队列（各自独立的 stream / group，互不干扰）----

    @Bean
    public DocumentTaskQueue documentTaskQueue(
            StringRedisTemplate redis,
            RedisBackend backend,
            @Qualifier("documentTaskPolicy") TaskPolicy policy) {
        return new RedisDocumentTaskQueue(redis, policy, backend);
    }

    @Bean
    public EvalRunTaskQueue evalRunTaskQueue(
            StringRedisTemplate redis,
            RedisBackend backend,
            @Qualifier("evalRunTaskPolicy") TaskPolicy policy) {
        return new RedisEvalRunTaskQueue(redis, policy, backend);
    }

    // ---- 四个角色：一个进程只装一个（两条链各一对 publisher/consumer）----

    @Bean
    @ConditionalOnProperty(name = "recalldesk.worker.role", havingValue = "document-publisher")
    public ApplicationRunner documentTaskPublisherRole(
            DocumentTaskQueue queue,
            DocumentTaskRepository outbox,
            UnitOfWork unitOfWork,
            @Qualifier("documentTaskPolicy") TaskPolicy policy) {
        return new WorkerRunner(
                "recalldesk-document-publisher",
                new DocumentTaskPublisher(unitOfWork, outbox, queue, policy));
    }

    @Bean
    @ConditionalOnProperty(name = "recalldesk.worker.role", havingValue = "document-consumer")
    public ApplicationRunner documentTaskConsumerRole(
            DocumentTaskQueue queue,
            DocumentRepository documents,
            DocumentTaskRepository outbox,
            DocumentFileStorage fileStorage,
            IndexingService indexingService,
            UnitOfWork unitOfWork,
            @Qualifier("documentTaskPolicy") TaskPolicy policy) {
        return new WorkerRunner(
                "recalldesk-document-consumer",
                new DocumentTaskConsumer(queue, unitOfWork, policy, documents, outbox, fileStorage, indexingService));
    }

    @Bean
    @ConditionalOnProperty(name = "recalldesk.worker.role", havingValue = "eval-run-publisher")
    public ApplicationRunner evalRunTaskPublisherRole(
            EvalRunTaskQueue queue,
            EvalRunTaskRepository tasks,
            EvalRunRepository evals,
            UnitOfWork unitOfWork,
            @Qualifier("evalRunTaskPolicy") TaskPolicy policy) {
        return new WorkerRunner(
                "recalldesk-eval-run-publisher",
                new EvalRunTaskPublisher(unitOfWork, tasks, evals, queue, policy));
    }

    @Bean
    @ConditionalOnProperty(name = "recalldesk.worker.role", havingValue = "eval-run-consumer")
    public ApplicationRunner evalRunConsumerRole(
            EvalRunTaskQueue queue,
            EvalRunTaskRepository runTasks,
            EvalRunRepository runs,
            EvalRepository catalog,
            SearchService searchService,
            UnitOfWork unitOfWork,
            @Qualifier("evalRunTaskPolicy") TaskPolicy policy) {
        return new WorkerRunner(
                "recalldesk-eval-run-consumer",
                new EvalRunConsumer(queue, unitOfWork, policy, runTasks, runs, catalog, searchService));
    }
}
