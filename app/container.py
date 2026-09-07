"""Dishka 依赖注入组合根。

这里把「接口（Protocol）→ 实现」绑定在一起，风格类似 C#/Java 的
DI 容器注册：AppProvider 里一个 provide 方法对应一次注册。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from dishka import AsyncContainer, Provider, Scope, make_async_container, provide
from redis.asyncio import Redis, from_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.application.services.consume.document_task_consumer import DocumentTaskConsumer
from app.application.services.consume.eval_question_consumer import EvalQuestionConsumer
from app.application.services.document_service import DocumentService
from app.application.services.eval_question_generator import EvalQuestionGenerator
from app.application.services.eval_run_executor import EvalRunExecutor
from app.application.services.eval_run_service import EvalRunService
from app.application.services.eval_service import EvalService
from app.application.services.indexing_service import IndexingService
from app.application.services.publish.document_task_publisher import DocumentTaskPublisher
from app.application.services.publish.eval_task_publisher import EvalTaskPublisher
from app.application.services.query_rewrite_service import QueryRewriteService
from app.application.services.search_service import SearchService
from app.application.services.split_service import SplitService
from app.infrastructure.csv_text_splitter import CsvTextSplitter
from app.infrastructure.db import build_engine, build_session_factory
from app.infrastructure.document_repository import SqlAlchemyDocumentRepository
from app.infrastructure.document_task_repository import SqlAlchemyDocumentTaskRepository
from app.infrastructure.eval_repository import SqlAlchemyEvalRepository
from app.infrastructure.eval_task_repository import SqlAlchemyEvalTaskRepository
from app.infrastructure.llama_index_embedding_client import LlamaIndexEmbeddingClient
from app.infrastructure.llama_index_llm_client import LlamaIndexLlmClient
from app.infrastructure.llama_index_text_splitter import LlamaIndexTextSplitter
from app.infrastructure.local_file_storage import LocalFileStorage
from app.infrastructure.ollama_qwen3_reranker import OllamaQwen3Reranker
from app.infrastructure.qdrant_repository import QdrantRepository
from app.infrastructure.queues import RedisDocumentTaskQueue, RedisEvalTaskQueue
from app.infrastructure.unit_of_work import SqlAlchemyUnitOfWork
from app.ports.document_file_storage import DocumentFileStorage
from app.ports.document_repository import DocumentRepository
from app.ports.document_task_repository import DocumentTaskRepository
from app.ports.embedding_client import EmbeddingClient
from app.ports.eval_repository import EvalRepository
from app.ports.eval_task_repository import EvalTaskRepository
from app.ports.llm_client import LlmClient
from app.ports.reranker import Reranker
from app.ports.task_queue import DocumentTaskQueue, EvalTaskQueue
from app.ports.text_splitter import TextSplitter
from app.ports.unit_of_work import UnitOfWork
from app.ports.vector_repository import VectorRepository
from settings import settings


class AppProvider(Provider):
    """注册全部依赖。"""

    # ---- 数据库 ----
    @provide(scope=Scope.APP)
    async def provide_engine(self) -> AsyncGenerator[AsyncEngine, None]:
        engine = build_engine()
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
        return RedisDocumentTaskQueue(redis)

    @provide(scope=Scope.APP)
    def provide_eval_task_queue(self, redis: Redis) -> EvalTaskQueue:
        return RedisEvalTaskQueue(redis)

    # ---- 端口 -> 实现 ----
    @provide(scope=Scope.REQUEST)
    def provide_repository(self, session: AsyncSession) -> DocumentRepository:
        return SqlAlchemyDocumentRepository(session)

    @provide(scope=Scope.REQUEST)
    def provide_document_task_repository(self, session: AsyncSession) -> DocumentTaskRepository:
        return SqlAlchemyDocumentTaskRepository(session)

    @provide(scope=Scope.REQUEST)
    def provide_eval_repository(self, session: AsyncSession) -> EvalRepository:
        return SqlAlchemyEvalRepository(session)

    @provide(scope=Scope.REQUEST)
    def provide_eval_task_repository(self, session: AsyncSession) -> EvalTaskRepository:
        return SqlAlchemyEvalTaskRepository(session)

    @provide(scope=Scope.REQUEST)
    def provide_unit_of_work(self, session: AsyncSession) -> UnitOfWork:
        return SqlAlchemyUnitOfWork(session)

    @provide(scope=Scope.APP)
    async def provide_file_storage(self) -> AsyncGenerator[DocumentFileStorage, None]:
        yield LocalFileStorage(settings.data_dir)

    @provide(scope=Scope.APP)
    async def provide_vector_repository(self) -> AsyncGenerator[VectorRepository, None]:
        repository = QdrantRepository(
            url=settings.qdrant_url,
            collection=settings.qdrant_collection,
            embedding_dim=settings.qdrant_embedding_dim,
            api_key=settings.qdrant_api_key,
            bm25_model=settings.qdrant_bm25_model,
            bm25_options=settings.qdrant_bm25_options,
        )
        await repository.ensure_collection()  # 组装时 fail fast：Qdrant 不可用直接暴露
        yield repository
        await repository.close()

    @provide(scope=Scope.APP)
    def provide_embedding_client(self) -> EmbeddingClient:
        return LlamaIndexEmbeddingClient(
            model_name=settings.embedding_model,
            api_base=settings.embedding_base_url,
            api_key=settings.embedding_api_key,
        )

    @provide(scope=Scope.APP)
    def provide_search_service(
        self,
        repository: VectorRepository,
        embedding_client: EmbeddingClient,
        llm_client: LlmClient,
        reranker: Reranker,
    ) -> SearchService:
        rewriter = None
        if settings.query_rewrite_enabled and settings.llm_base_url and settings.llm_model:
            rewriter = QueryRewriteService(llm_client=llm_client)
        return SearchService(
            repository=repository,
            embedding_client=embedding_client,
            default_top_k=settings.top_k,
            rewriter=rewriter,
            reranker=reranker if settings.rerank_enabled else None,
            rerank_top_n=settings.rerank_top_n,
        )

    @provide(scope=Scope.APP)
    def provide_indexing_service(
        self,
        repository: VectorRepository,
        embedding_client: EmbeddingClient,
        split_service: SplitService,
    ) -> IndexingService:
        return IndexingService(
            repository=repository,
            embedding_client=embedding_client,
            split_service=split_service,
        )

    @provide(scope=Scope.APP)
    def provide_llm_client(self) -> LlmClient:
        return LlamaIndexLlmClient(
            model=settings.llm_model,
            api_base=settings.llm_base_url,
            api_key=settings.llm_api_key or "EMPTY",  # openai 客户端要求非空
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout,
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
        return DocumentTaskPublisher(session_factory=session_factory, queue=queue)

    @provide(scope=Scope.APP)
    def provide_document_task_consumer(
        self,
        queue: DocumentTaskQueue,
        session_factory: async_sessionmaker[AsyncSession],
        file_storage: DocumentFileStorage,
        indexing_service: IndexingService,
    ) -> DocumentTaskConsumer:
        return DocumentTaskConsumer(
            queue=queue,
            session_factory=session_factory,
            file_storage=file_storage,
            indexing_service=indexing_service,
        )

    # ---- Eval 后台任务 ----
    @provide(scope=Scope.APP)
    def provide_eval_task_publisher(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        queue: EvalTaskQueue,
    ) -> EvalTaskPublisher:
        return EvalTaskPublisher(session_factory=session_factory, queue=queue)

    @provide(scope=Scope.APP)
    def provide_eval_question_generator(self, llm_client: LlmClient) -> EvalQuestionGenerator:
        return EvalQuestionGenerator(llm_client=llm_client)

    @provide(scope=Scope.APP)
    def provide_eval_question_consumer(
        self,
        queue: EvalTaskQueue,
        session_factory: async_sessionmaker[AsyncSession],
        question_generator: EvalQuestionGenerator,
        vector_repository: VectorRepository,
    ) -> EvalQuestionConsumer:
        return EvalQuestionConsumer(
            queue=queue,
            session_factory=session_factory,
            question_generator=question_generator,
            vector_repository=vector_repository,
        )

    @provide(scope=Scope.APP)
    def provide_eval_run_executor(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        search_service: SearchService,
    ) -> EvalRunExecutor:
        return EvalRunExecutor(
            session_factory=session_factory,
            search_service=search_service,
        )

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
        vector_repository: VectorRepository,
    ) -> DocumentService:
        return DocumentService(
            repository=repository,
            unit_of_work=unit_of_work,
            file_storage=file_storage,
            outbox=outbox,
            split_service=split_service,
            search_service=search_service,
            vector_repository=vector_repository,
        )

    @provide(scope=Scope.REQUEST)
    def provide_eval_service(
        self,
        eval_repository: EvalRepository,
        eval_task_repository: EvalTaskRepository,
        repository: DocumentRepository,
        vector_repository: VectorRepository,
        unit_of_work: UnitOfWork,
    ) -> EvalService:
        return EvalService(
            eval_repository=eval_repository,
            eval_task_repository=eval_task_repository,
            documents=repository,
            vector_repository=vector_repository,
            unit_of_work=unit_of_work,
        )

    @provide(scope=Scope.REQUEST)
    def provide_eval_run_service(
        self,
        eval_repository: EvalRepository,
        unit_of_work: UnitOfWork,
        executor: EvalRunExecutor,
        search_service: SearchService,
    ) -> EvalRunService:
        return EvalRunService(
            eval_repository=eval_repository,
            unit_of_work=unit_of_work,
            executor=executor,
            # 只要它的 rewrite_enabled 记进 run 的配置快照，不在这里检索
            search_service=search_service,
            default_top_k=settings.top_k,
        )


def create_container() -> AsyncContainer:
    return make_async_container(AppProvider())


__all__ = ["AppProvider", "create_container"]
