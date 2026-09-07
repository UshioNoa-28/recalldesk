"""任务消费者：从队列消费任务，执行文档的索引与向量清理。

设计说明：
- APP 作用域后台循环，注入 session_factory 自管短事务；
- 只依赖 DocumentTaskQueue 接口，不碰 Redis 细节；
- 按消息里的 operation 分派：index 建向量，delete 删向量。删除任务的 documents
  行注定已经没了，所以「文档不存在」不能当成跳过；
- ACK 规则：commit 成功就 ACK（业务成功或失败落库都是），只有 commit
  本身失败才不 ACK，留给 XAUTOCLAIM 恢复；
- 业务失败的重试靠 task 回 PENDING（指数退避），由 DocumentTaskPublisher 重新
  投递，避免毒丸消息阻塞队列；
- 消费者崩溃留下的未 ACK 消息由队列的 claim_orphans 认领。
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.services.indexing_service import EmptyContentError, IndexingService
from app.domain.documents import DocumentStatus
from app.infrastructure.document_repository import SqlAlchemyDocumentRepository
from app.infrastructure.document_task_repository import SqlAlchemyDocumentTaskRepository
from app.infrastructure.file_text_extractor import extract_file_text
from app.ports.document_file_storage import DocumentFileStorage
from app.ports.task_queue import DocumentTaskQueue
from settings import settings

logger = logging.getLogger(__name__)


class DocumentTaskConsumer:
    """不停消费队列任务，执行索引并回写状态。

    本服务独占一个进程/容器，索引调用直接阻塞事件循环即可，
    不需要丢线程池。
    """

    def __init__(
        self,
        *,
        queue: DocumentTaskQueue,
        session_factory: async_sessionmaker,
        file_storage: DocumentFileStorage,
        indexing_service: IndexingService,
        consumer_name: str | None = None,
    ) -> None:
        self._queue = queue
        self._session_factory = session_factory
        self._file_storage = file_storage
        self._indexing_service = indexing_service
        self._consumer_name = consumer_name or f"consumer-{os.getpid()}"
        self._stop_event = asyncio.Event()

    async def run(self, stop_event: asyncio.Event) -> None:
        logger.info("启动 DocumentTaskConsumer: consumer=%s", self._consumer_name)
        await self._queue.ensure_consumer_group()
        while not stop_event.is_set():
            try:
                await self._claim_and_process_orphans()
                messages = await self._queue.read_new(
                    consumer_name=self._consumer_name,
                    count=1,
                    block_ms=2000,
                )
                for message_id, data in messages:
                    await self._process_single_message(message_id, data)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("DocumentTaskConsumer 消费循环异常")
                await asyncio.sleep(1.0)

    async def _claim_and_process_orphans(self) -> None:
        """认领空闲超时的未确认消息（消费者崩溃遗留）。"""

        try:
            claimed = await self._queue.claim_orphans(
                consumer_name=self._consumer_name,
                count=2,
            )
            for message_id, data in claimed:
                logger.warning("认领孤儿任务: id=%s data=%s", message_id, data)
                await self._process_single_message(message_id, data)
        except Exception:
            logger.warning("认领孤儿任务异常（非致命）", exc_info=True)

    async def _process_single_message(self, message_id: str, data: dict[str, Any]) -> None:
        """处理单条消息；commit 成功才 ACK，失败留给 XAUTOCLAIM。"""

        task_id = data.get("task_id")
        document_id = data.get("document_id")
        if not task_id or not document_id:
            logger.error("消息缺少 task_id/document_id，直接 ACK: msg_id=%s", message_id)
            await self._queue.ack(message_id)
            return

        # 老消息没有 operation 字段，按索引处理
        operation = data.get("operation") or "index"
        logger.info(
            "处理任务: msg_id=%s task=%s doc=%s op=%s",
            message_id,
            task_id,
            document_id,
            operation,
        )
        try:
            await self._handle_task(
                task_id=task_id, document_id=document_id, operation=operation
            )
        except Exception:
            # 事务提交失败等未预期异常：不 ACK，消息留在 PEL，
            # 由 XAUTOCLAIM 认领重试（DB 状态未变，幂等）。
            logger.exception("任务处理异常（不 ACK，等待认领）: task=%s", task_id)
            return
        await self._queue.ack(message_id)

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
            outbox = SqlAlchemyDocumentTaskRepository(session)
            documents = SqlAlchemyDocumentRepository(session)

            if operation == "delete":
                # documents 行就是被删掉的那个，所以不能走下面「文档不存在即成功」
                # 那条短路。删不存在的点是空操作，整条幂等；Qdrant 出错时直接抛出，
                # 消息不 ACK、由 claim_orphans 重投 —— 已经没有文档行可以记业务失败了。
                await self._indexing_service.delete(document_id)
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
                if entry is not None and entry.attempts >= settings.task_max_attempts:
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
            document.status = DocumentStatus.SUCCESS
            document.chunk_count = chunk_count
            document.indexed_at = datetime.now(UTC)
            await documents.update(document)
            await session.commit()


__all__ = ["DocumentTaskConsumer"]
