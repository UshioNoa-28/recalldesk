"""Dishka 依赖注入组合根。

这里把「接口（Protocol）→ 实现」绑定在一起，风格类似 C#/Java 的
DI 容器注册：AppProvider 里一个 provide 方法对应一次注册。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from dishka import AsyncContainer, Provider, Scope, make_async_container, provide
from neo4j import AsyncDriver, AsyncGraphDatabase
from redis.asyncio import Redis, from_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.application.services.consume.document_task_consumer import DocumentTaskConsumer
from app.application.services.consume.eval_question_consumer import EvalQuestionConsumer
from app.application.services.consume.eval_run_consumer import EvalRunConsumer
from app.application.services.consume.graph_task_consumer import GraphTaskConsumer
from app.application.services.document.document_service import DocumentService
from app.application.services.document.indexing_service import IndexingService
from app.application.services.document.split_service import SplitService
from app.application.services.evaluation.eval_question_generator import EvalQuestionGenerator
from app.application.services.evaluation.eval_run_service import EvalRunService
from app.application.services.evaluation.eval_service import EvalService
from app.application.services.graph.graph_channel import GraphRecallChannel
from app.application.services.graph.graph_explorer_service import GraphExplorerService
from app.application.services.graph.graph_extraction_service import GraphExtractionService
from app.application.services.publish.document_task_publisher import DocumentTaskPublisher
from app.application.services.publish.eval_run_task_publisher import EvalRunTaskPublisher
from app.application.services.publish.eval_task_publisher import EvalTaskPublisher
from app.application.services.publish.graph_task_publisher import GraphTaskPublisher
from app.application.services.search.query_rewrite_service import QueryRewriteService
from app.application.services.search.search_service import SearchService
from app.config import RedisBackend, TaskPolicy, UploadLimits, parse_allowed_extensions
from app.infrastructure.local_file_storage import LocalFileStorage
from app.infrastructure.model_clients.llama_index_embedding_client import LlamaIndexEmbeddingClient
from app.infrastructure.model_clients.llama_index_llm_client import LlamaIndexLlmClient
from app.infrastructure.model_clients.ollama_qwen3_reranker import OllamaQwen3Reranker
from app.infrastructure.neo4j.chunk_index import Neo4jChunkIndex
from app.infrastructure.neo4j.graph_repository import Neo4jGraphRepository
from app.infrastructure.postgres.db import build_engine, build_session_factory
from app.infrastructure.postgres.document_repository import SqlAlchemyDocumentRepository
from app.infrastructure.postgres.document_task_repository import SqlAlchemyDocumentTaskRepository
from app.infrastructure.postgres.eval_repository import SqlAlchemyEvalRepository
from app.infrastructure.postgres.eval_run_repository import SqlAlchemyEvalRunRepository
from app.infrastructure.postgres.eval_run_task_repository import SqlAlchemyEvalRunTaskRepository
from app.infrastructure.postgres.eval_task_repository import SqlAlchemyEvalTaskRepository
from app.infrastructure.postgres.graph_task_repository import SqlAlchemyGraphTaskRepository
from app.infrastructure.postgres.unit_of_work import SqlAlchemyUnitOfWork
from app.infrastructure.redis import (
    RedisDocumentTaskQueue,
    RedisEvalRunTaskQueue,
    RedisEvalTaskQueue,
    RedisGraphTaskQueue,
)
from app.infrastructure.text.csv_text_splitter import CsvTextSplitter
from app.infrastructure.text.llama_index_text_splitter import LlamaIndexTextSplitter
from app.ports.chunk_index import ChunkIndex
from app.ports.document_file_storage import DocumentFileStorage
from app.ports.graph_repository import GraphRepository
from app.ports.model_clients.embedding_client import EmbeddingClient
from app.ports.model_clients.llm_client import LlmClient
from app.ports.model_clients.reranker import Reranker
from app.ports.persistence.document_repository import DocumentRepository
from app.ports.persistence.document_task_repository import DocumentTaskRepository
from app.ports.persistence.eval_repository import EvalRepository
from app.ports.persistence.eval_run_repository import EvalRunRepository
from app.ports.persistence.eval_run_task_repository import EvalRunTaskRepository
from app.ports.persistence.eval_task_repository import EvalTaskRepository
from app.ports.persistence.graph_task_repository import GraphTaskRepository
from app.ports.persistence.unit_of_work import UnitOfWork
from app.ports.task_queue import DocumentTaskQueue, EvalRunTaskQueue, EvalTaskQueue, GraphTaskQueue
from app.ports.text_splitter import TextSplitter
from settings import settings


class AppProvider(Provider):
    """注册全部依赖。

    settings 只在这里读一次，切成 config 里的分组值对象（self._*）再注入下游；
    仓储 / 队列 / publisher / consumer / 控制器都不再自己 `import settings`。
    """

    def __init__(self) -> None:
        super().__init__()
        self.database_url = settings.database_url
        self._redis_backend = RedisBackend(
            maxlen=settings.redis_stream_maxlen,
            claim_min_idle_ms=settings.redis_claim_min_idle_ms,
            claim_start_id=settings.redis_claim_start_id,
        )
        self._doc_policy = TaskPolicy(
            stream=settings.redis_document_task_stream,
            consumer_group=settings.redis_document_consumer_group,
            publish_interval_seconds=settings.task_publish_interval_seconds,
            publish_batch_size=settings.task_publish_batch_size,
            max_attempts=settings.task_max_attempts,
            retry_backoff_seconds=settings.task_retry_backoff_base_seconds,
        )
        self._eval_policy = TaskPolicy(
            stream=settings.redis_eval_task_stream,
            consumer_group=settings.redis_eval_consumer_group,
            publish_interval_seconds=settings.eval_task_publish_interval_seconds,
            publish_batch_size=settings.eval_task_publish_batch_size,
            max_attempts=settings.eval_task_max_attempts,
            retry_backoff_seconds=settings.eval_task_retry_backoff_base_seconds,
        )
        self._run_policy = TaskPolicy(
            stream=settings.redis_eval_run_task_stream,
            consumer_group=settings.redis_eval_run_consumer_group,
            publish_interval_seconds=settings.eval_run_task_publish_interval_seconds,
            publish_batch_size=settings.eval_run_task_publish_batch_size,
            max_attempts=settings.eval_run_task_max_attempts,
            retry_backoff_seconds=settings.eval_run_task_retry_backoff_base_seconds,
        )
        self._upload_limits = UploadLimits(
            max_bytes=settings.max_file_size_bytes,
            allowed_suffixes=parse_allowed_extensions(settings.allowed_extensions),
        )
        self._doc_backoff = self._doc_policy.retry_backoff_seconds
        self._eval_backoff = self._eval_policy.retry_backoff_seconds
        self._run_backoff = self._run_policy.retry_backoff_seconds
        self._graph_policy = TaskPolicy(
            stream=settings.redis_graph_task_stream,
            consumer_group=settings.redis_graph_consumer_group,
            publish_interval_seconds=settings.graph_task_publish_interval_seconds,
            publish_batch_size=settings.graph_task_publish_batch_size,
            max_attempts=settings.graph_task_max_attempts,
            retry_backoff_seconds=settings.graph_task_retry_backoff_base_seconds,
        )

    # ---- 数据库 ----
    @provide(scope=Scope.APP)
    async def provide_engine(self) -> AsyncGenerator[AsyncEngine, None]:
        engine = build_engine(self.database_url)
        yield engine
        await engine.dispose()

    @provide(scope=Scope.APP)
    def provide_session_factory(
        self,
        engine: AsyncEngine,
    ) -> async_sessionmaker[AsyncSession]:
        return build_session_factory(engine)

    @provide(scope=Scope.REQUEST)
    async def provide_session(
        self,
        factory: async_sessionmaker[AsyncSession],
    ) -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    # ---- Redis ----
    @provide(scope=Scope.APP)
    async def provide_redis(self) -> AsyncGenerator[Redis, None]:
        client: Redis = from_url(settings.redis_url, decode_responses=True)
        yield client
        await client.aclose()

    @provide(scope=Scope.APP)
    def provide_document_task_queue(self, redis: Redis) -> DocumentTaskQueue:
        return RedisDocumentTaskQueue(redis, policy=self._doc_policy, backend=self._redis_backend)

    @provide(scope=Scope.APP)
    def provide_eval_task_queue(self, redis: Redis) -> EvalTaskQueue:
        return RedisEvalTaskQueue(redis, policy=self._eval_policy, backend=self._redis_backend)

    @provide(scope=Scope.APP)
    def provide_eval_run_task_queue(self, redis: Redis) -> EvalRunTaskQueue:
        return RedisEvalRunTaskQueue(redis, policy=self._run_policy, backend=self._redis_backend)

    # ---- 端口 -> 实现 ----
    @provide(scope=Scope.REQUEST)
    def provide_repository(self, session: AsyncSession) -> DocumentRepository:
        return SqlAlchemyDocumentRepository(session)

    @provide(scope=Scope.REQUEST)
    def provide_document_task_repository(self, session: AsyncSession) -> DocumentTaskRepository:
        return SqlAlchemyDocumentTaskRepository(session, retry_backoff_seconds=self._doc_backoff)

    @provide(scope=Scope.REQUEST)
    def provide_eval_repository(self, session: AsyncSession) -> EvalRepository:
        return SqlAlchemyEvalRepository(session)

    @provide(scope=Scope.REQUEST)
    def provide_eval_run_repository(self, session: AsyncSession) -> EvalRunRepository:
        return SqlAlchemyEvalRunRepository(session)

    @provide(scope=Scope.REQUEST)
    def provide_eval_task_repository(self, session: AsyncSession) -> EvalTaskRepository:
        return SqlAlchemyEvalTaskRepository(session, retry_backoff_seconds=self._eval_backoff)

    @provide(scope=Scope.REQUEST)
    def provide_eval_run_task_repository(
        self, session: AsyncSession
    ) -> EvalRunTaskRepository:
        return SqlAlchemyEvalRunTaskRepository(session, retry_backoff_seconds=self._run_backoff)

    @provide(scope=Scope.REQUEST)
    def provide_unit_of_work(self, session: AsyncSession) -> UnitOfWork:
        return SqlAlchemyUnitOfWork(session)

    @provide(scope=Scope.APP)
    async def provide_file_storage(self) -> AsyncGenerator[DocumentFileStorage, None]:
        yield LocalFileStorage(settings.data_dir)

    # ---- Neo4j：chunk 检索索引（向量 + 全文），后续图也住这里 ----
    @provide(scope=Scope.APP)
    async def provide_neo4j_driver(self) -> AsyncGenerator[AsyncDriver, None]:
        driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
        yield driver
        await driver.close()

    @provide(scope=Scope.APP)
    async def provide_chunk_index(self, driver: AsyncDriver) -> AsyncGenerator[ChunkIndex, None]:
        index = Neo4jChunkIndex(
            driver,
            embedding_dim=settings.embedding_dim,
            analyzer=settings.chunk_fulltext_analyzer,
        )
        await index.ensure_indexes()  # 组装时 fail fast：引擎不可用/维度不符直接暴露
        yield index

    # ---- 知识图谱：Neo4j 图存储 + 抽取链路（第四条 outbox） ----
    @provide(scope=Scope.APP)
    async def provide_graph_repository(
        self, driver: AsyncDriver
    ) -> AsyncGenerator[GraphRepository, None]:
        store = Neo4jGraphRepository(
            driver,
            embedding_dim=settings.embedding_dim,
            analyzer=settings.chunk_fulltext_analyzer,
        )
        await store.ensure_indexes()  # 组装期 fail fast，同 chunk 索引的纪律
        yield store

    @provide(scope=Scope.APP)
    def provide_graph_task_queue(self, redis: Redis) -> GraphTaskQueue:
        return RedisGraphTaskQueue(redis, policy=self._graph_policy, backend=self._redis_backend)

    @provide(scope=Scope.REQUEST)
    def provide_graph_task_repository(self, session: AsyncSession) -> GraphTaskRepository:
        return SqlAlchemyGraphTaskRepository(
            session, retry_backoff_seconds=self._graph_policy.retry_backoff_seconds
        )

    @provide(scope=Scope.APP)
    def provide_graph_extraction_service(
        self,
        llm_client: LlmClient,
        embedding_client: EmbeddingClient,
    ) -> GraphExtractionService:
        return GraphExtractionService(
            llm_client=llm_client,
            embedding_client=embedding_client,
            concurrency=settings.graph_extract_concurrency,
        )

    @provide(scope=Scope.APP)
    def provide_graph_task_publisher(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        queue: GraphTaskQueue,
    ) -> GraphTaskPublisher:
        return GraphTaskPublisher(
            session_factory=session_factory, queue=queue, policy=self._graph_policy
        )

    @provide(scope=Scope.APP)
    def provide_graph_task_consumer(
        self,
        queue: GraphTaskQueue,
        session_factory: async_sessionmaker[AsyncSession],
        graph_extraction_service: GraphExtractionService,
        graph_repository: GraphRepository,
        chunk_index: ChunkIndex,
    ) -> GraphTaskConsumer:
        return GraphTaskConsumer(
            queue=queue,
            session_factory=session_factory,
            extraction_service=graph_extraction_service,
            graph=graph_repository,
            chunk_index=chunk_index,
            policy=self._graph_policy,
        )

    @provide(scope=Scope.APP)
    def provide_embedding_client(self) -> EmbeddingClient:
        return LlamaIndexEmbeddingClient(
            model_name=settings.embedding_model,
            api_base=settings.embedding_base_url,
            api_key=settings.embedding_api_key,
        )

    @provide(scope=Scope.APP)
    def provide_graph_recall_channel(self, graph_repository: GraphRepository) -> GraphRecallChannel:
        """种子链接 + k 跳扩展的通道对象：检索路按开关注入，浏览器无条件用。

        构建零成本（纯包装），graph_enabled=false 时它不挂进 SearchService，
        但 /graph/* 浏览端点照样能读图——抽取链路与检索开关本就独立。
        """

        return GraphRecallChannel(
            graph_repository,
            hops=settings.graph_hops,
            candidates=settings.graph_candidates,
            link_min_score=settings.graph_link_min_score,
        )

    @provide(scope=Scope.APP)
    def provide_graph_explorer_service(
        self,
        graph_repository: GraphRepository,
        channel: GraphRecallChannel,
        embedding_client: EmbeddingClient,
    ) -> GraphExplorerService:
        return GraphExplorerService(
            store=graph_repository, channel=channel, embedding_client=embedding_client
        )

    @provide(scope=Scope.APP)
    def provide_search_service(
        self,
        index: ChunkIndex,
        embedding_client: EmbeddingClient,
        llm_client: LlmClient,
        reranker: Reranker,
        graph_channel: GraphRecallChannel,
    ) -> SearchService:
        rewriter = None
        if settings.query_rewrite_enabled and settings.llm_base_url and settings.llm_model:
            rewriter = QueryRewriteService(llm_client=llm_client)
        return SearchService(
            index=index,
            embedding_client=embedding_client,
            default_top_k=settings.top_k,
            rewriter=rewriter,
            reranker=reranker if settings.rerank_enabled else None,
            rerank_top_n=settings.rerank_top_n,
            graph=graph_channel if settings.graph_enabled else None,
        )

    @provide(scope=Scope.APP)
    def provide_indexing_service(
        self,
        index: ChunkIndex,
        embedding_client: EmbeddingClient,
        split_service: SplitService,
    ) -> IndexingService:
        return IndexingService(
            index=index,
            embedding_client=embedding_client,
            split_service=split_service,
        )

    @provide(scope=Scope.APP)
    def provide_llm_client(self) -> LlmClient:
        return LlamaIndexLlmClient(
            model=settings.llm_model,
            api_base=settings.llm_base_url,
            api_key=settings.llm_api_key,
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout,
            extra_body=settings.llm_extra_body,
        )

    @provide(scope=Scope.APP)
    def provide_reranker(self) -> Reranker:
        return OllamaQwen3Reranker(
            base_url=settings.rerank_ollama_url,
            model=settings.rerank_model,
            candidate_chars=settings.rerank_candidate_chars,
            timeout=settings.rerank_timeout_seconds,
            num_ctx=settings.rerank_num_ctx,
            concurrency=settings.rerank_concurrency,
        )

    @provide(scope=Scope.APP)
    def provide_text_splitter(self) -> TextSplitter:
        return LlamaIndexTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )

    # 端口类型 TextSplitter 已经被句子分块器占了，CSV 这个按具体类作 key
    @provide(scope=Scope.APP)
    def provide_csv_splitter(self) -> CsvTextSplitter:
        return CsvTextSplitter(chunk_size=settings.chunk_size)

    @provide(scope=Scope.APP)
    def provide_split_service(
        self,
        text_splitter: TextSplitter,
        csv_splitter: CsvTextSplitter,
    ) -> SplitService:
        return SplitService(text_splitter=text_splitter, csv_splitter=csv_splitter)

    # ---- 后台任务 ----
    @provide(scope=Scope.APP)
    def provide_document_task_publisher(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        queue: DocumentTaskQueue,
    ) -> DocumentTaskPublisher:
        return DocumentTaskPublisher(
            session_factory=session_factory,
            queue=queue,
            policy=self._doc_policy,
        )

    @provide(scope=Scope.APP)
    def provide_document_task_consumer(
        self,
        queue: DocumentTaskQueue,
        session_factory: async_sessionmaker[AsyncSession],
        file_storage: DocumentFileStorage,
        indexing_service: IndexingService,
        graph_repository: GraphRepository,
    ) -> DocumentTaskConsumer:
        return DocumentTaskConsumer(
            queue=queue,
            session_factory=session_factory,
            file_storage=file_storage,
            indexing_service=indexing_service,
            policy=self._doc_policy,
            graph=graph_repository,
            graph_enabled=settings.graph_enabled,
            graph_backoff_seconds=self._graph_policy.retry_backoff_seconds,
        )

    # ---- Eval 后台任务 ----
    @provide(scope=Scope.APP)
    def provide_eval_task_publisher(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        queue: EvalTaskQueue,
    ) -> EvalTaskPublisher:
        return EvalTaskPublisher(
            session_factory=session_factory,
            queue=queue,
            policy=self._eval_policy,
        )

    @provide(scope=Scope.APP)
    def provide_eval_run_task_publisher(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        queue: EvalRunTaskQueue,
    ) -> EvalRunTaskPublisher:
        return EvalRunTaskPublisher(
            session_factory=session_factory,
            queue=queue,
            policy=self._run_policy,
        )

    @provide(scope=Scope.APP)
    def provide_eval_question_generator(self, llm_client: LlmClient) -> EvalQuestionGenerator:
        return EvalQuestionGenerator(llm_client=llm_client)

    @provide(scope=Scope.APP)
    def provide_eval_question_consumer(
        self,
        queue: EvalTaskQueue,
        session_factory: async_sessionmaker[AsyncSession],
        question_generator: EvalQuestionGenerator,
        chunk_index: ChunkIndex,
    ) -> EvalQuestionConsumer:
        return EvalQuestionConsumer(
            queue=queue,
            session_factory=session_factory,
            question_generator=question_generator,
            chunk_index=chunk_index,
            policy=self._eval_policy,
        )

    @provide(scope=Scope.APP)
    def provide_eval_run_consumer(
        self,
        queue: EvalRunTaskQueue,
        session_factory: async_sessionmaker[AsyncSession],
        search_service: SearchService,
    ) -> EvalRunConsumer:
        return EvalRunConsumer(
            queue=queue,
            session_factory=session_factory,
            search_service=search_service,
            policy=self._run_policy,
        )

    @provide(scope=Scope.APP)
    def provide_upload_limits(self) -> UploadLimits:
        return self._upload_limits

    # ---- 应用服务 ----
    @provide(scope=Scope.REQUEST)
    def provide_document_service(
        self,
        repository: DocumentRepository,
        unit_of_work: UnitOfWork,
        file_storage: DocumentFileStorage,
        outbox: DocumentTaskRepository,
        split_service: SplitService,
        search_service: SearchService,
        chunk_index: ChunkIndex,
        eval_repository: EvalRepository,
        graph_task_repository: GraphTaskRepository,
    ) -> DocumentService:
        return DocumentService(
            repository=repository,
            unit_of_work=unit_of_work,
            file_storage=file_storage,
            outbox=outbox,
            split_service=split_service,
            search_service=search_service,
            chunk_index=chunk_index,
            eval_repository=eval_repository,
            graph_tasks=graph_task_repository,
            graph_enabled=settings.graph_enabled,
        )

    @provide(scope=Scope.REQUEST)
    def provide_eval_service(
        self,
        eval_repository: EvalRepository,
        eval_task_repository: EvalTaskRepository,
        repository: DocumentRepository,
        chunk_index: ChunkIndex,
        unit_of_work: UnitOfWork,
    ) -> EvalService:
        return EvalService(
            eval_repository=eval_repository,
            eval_task_repository=eval_task_repository,
            documents=repository,
            chunk_index=chunk_index,
            unit_of_work=unit_of_work,
        )

    @provide(scope=Scope.REQUEST)
    def provide_eval_run_service(
        self,
        eval_repository: EvalRepository,
        run_repository: EvalRunRepository,
        run_tasks: EvalRunTaskRepository,
        unit_of_work: UnitOfWork,
        search_service: SearchService,
    ) -> EvalRunService:
        return EvalRunService(
            eval_repository=eval_repository,
            run_repository=run_repository,
            run_tasks=run_tasks,
            unit_of_work=unit_of_work,
            # 只要它的 rewrite_enabled 记进 run 的配置快照，不在这里检索
            search_service=search_service,
            default_top_k=settings.top_k,
        )


def create_container() -> AsyncContainer:
    return make_async_container(AppProvider())


__all__ = ["AppProvider", "create_container"]
