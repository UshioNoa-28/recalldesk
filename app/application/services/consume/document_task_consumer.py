"""任务消费者：从队列消费任务，执行文档的索引与向量清理。

设计说明（消费循环 / ACK 规则见 BaseConsumer）：
- APP 作用域后台循环，注入 session_factory 自管短事务；
- 只依赖 DocumentTaskQueue 接口，不碰 Redis 细节；
- 按消息里的 operation 分派：index 建向量，delete 删向量。删除任务的 documents
  行注定已经没了，所以「文档不存在」不能当成跳过；
- 业务失败的重试靠 task 回 PENDING（指数退避），由 DocumentTaskPublisher 重新
  投递，避免毒丸消息阻塞队列。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.services.consume.base_consumer import BaseConsumer
from app.application.services.document.indexing_service import EmptyContentError, IndexingService
from app.config import DOCUMENT_TASK_POLICY, TaskPolicy
from app.domain.documents import DocumentStatus
from app.infrastructure.postgres.document_repository import SqlAlchemyDocumentRepository
from app.infrastructure.postgres.document_task_repository import SqlAlchemyDocumentTaskRepository
from app.infrastructure.postgres.graph_task_repository import SqlAlchemyGraphTaskRepository
from app.infrastructure.text.file_text_extractor import extract_file_text
from app.ports.document_file_storage import DocumentFileStorage
from app.ports.graph_repository import GraphRepository
from app.ports.task_queue import DocumentTaskQueue

logger = logging.getLogger(__name__)


class DocumentTaskConsumer(BaseConsumer):
    """不停消费队列任务，执行索引并回写状态。"""

    def __init__(
        self,
        *,
        queue: DocumentTaskQueue,
        session_factory: async_sessionmaker,
        file_storage: DocumentFileStorage,
        indexing_service: IndexingService,
        consumer_name: str | None = None,
        policy: TaskPolicy = DOCUMENT_TASK_POLICY,
        graph: GraphRepository | None = None,
        graph_enabled: bool = False,
        graph_backoff_seconds: float = 30.0,
    ) -> None:
        super().__init__(
            queue=queue,
            session_factory=session_factory,
            policy=policy,
            consumer_name=consumer_name,
        )
        self._file_storage = file_storage
        self._indexing_service = indexing_service
        self._graph = graph
        self._graph_enabled = graph_enabled
        self._graph_backoff = graph_backoff_seconds

    def _extract_task_ids(self, data: dict[str, Any]) -> dict[str, str] | None:
        task_id = data.get("task_id")
        document_id = data.get("document_id")
        if not task_id or not document_id:
            return None
        # 老消息没有 operation 字段，按索引处理
        return {
            "task_id": task_id,
            "document_id": document_id,
            "operation": data.get("operation") or "index",
        }

    async def _handle_task(
        self, *, task_id: str, document_id: str, operation: str
    ) -> None:
        """按 operation 分派：index 建向量，delete 删向量。

        业务失败在本方法内落库并正常返回（由调用方 ACK）；
        只有 commit 失败才会抛出。失败时：attempts+1、task 回 PENDING
        （指数退避，等 DocumentTaskPublisher 重新投递）；超限则 task 和 document
        都标 FAILED。
        """

        async with self._session_factory() as session:
            outbox = SqlAlchemyDocumentTaskRepository(session, retry_backoff_seconds=self._backoff)
            documents = SqlAlchemyDocumentRepository(session)

            if operation == "delete":
                # documents 行就是被删掉的那个，所以不能走下面「文档不存在即成功」
                # 那条短路。删不存在的块是空操作，整条幂等；索引端出错时直接抛出，
                # 消息不 ACK、由 claim_orphans 重投 —— 已经没有文档行可以记业务失败了。
                await self._indexing_service.delete(document_id)
                if self._graph is not None:
                    # 图库没有 FK CASCADE：删除链路顺手清本篇贡献（幂等，失败重投）
                    await self._graph.delete_document_graph(document_id)
                await outbox.mark_success(task_id)
                await session.commit()
                return

            document = await documents.get(document_id)
            if document is None:
                # 文档已不存在，任务直接算成功（幂等）
                await outbox.mark_success(task_id)
                await session.commit()
                return

            try:
                content = self._file_storage.read(storage_key=document.storage_key)
                text = extract_file_text(name=document.name, content=content)
                chunk_count = await self._indexing_service.ingest(
                    document.id,
                    document.name,
                    text,
                )
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                if isinstance(exc, EmptyContentError):
                    # 切不出分块是内容本身的问题，重试不会变好：直接终态，
                    # 不进指数退避（否则这类文档要白跑满 10 次重试才 FAILED）
                    await outbox.mark_failed(task_id)
                    document.status = DocumentStatus.FAILED
                    document.error_message = error
                    await documents.update(document)
                    logger.error(
                        "内容切不出分块，任务直接终态失败: task=%s doc=%s",
                        task_id,
                        document_id,
                    )
                    await session.commit()
                    return
                await outbox.record_failure(task_id, error=error)
                entry = await outbox.get(task_id)
                if entry is not None and entry.attempts >= self._policy.max_attempts:
                    await outbox.mark_failed(task_id)
                    document.status = DocumentStatus.FAILED
                    document.error_message = error
                    await documents.update(document)
                    logger.error(
                        "任务失败达到上限: task=%s doc=%s error=%s",
                        task_id,
                        document_id,
                        error,
                    )
                else:
                    logger.warning(
                        "任务失败（未超限，回 PENDING 等重投）: task=%s doc=%s error=%s",
                        task_id,
                        document_id,
                        error,
                    )
                await session.commit()
                return

            await outbox.mark_success(task_id)
            if self._graph_enabled:
                # 第四条链路：索引成功与抽取任务同事务入队（outbox 原子性）
                await SqlAlchemyGraphTaskRepository(
                    session, retry_backoff_seconds=self._graph_backoff
                ).add(document_id=document_id)
            document.status = DocumentStatus.SUCCESS
            document.chunk_count = chunk_count
            document.indexed_at = datetime.now(UTC)
            await documents.update(document)
            await session.commit()


__all__ = ["DocumentTaskConsumer"]
