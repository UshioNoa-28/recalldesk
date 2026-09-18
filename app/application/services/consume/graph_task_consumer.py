"""图谱抽取任务消费者：领一篇文档 → LLM 逐块抽取 → 整篇替换写入 Neo4j 图。

ACK/退避规则见 BaseConsumer；与索引链路的分工：索引链路成功那一刻把抽取任务
写进同一事务（outbox），这里异步消化——LLM 再慢也不拖累可检索性。
幂等：upsert_document_graph 是整篇替换 + 孤儿清扫，重投重跑无害。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.services.consume.base_consumer import BaseConsumer
from app.application.services.graph.graph_extraction_service import GraphExtractionService
from app.config import GRAPH_TASK_POLICY, TaskPolicy
from app.domain.graph import GraphTaskStatus
from app.infrastructure.postgres.document_repository import SqlAlchemyDocumentRepository
from app.infrastructure.postgres.graph_task_repository import SqlAlchemyGraphTaskRepository
from app.ports.chunk_index import ChunkIndex
from app.ports.graph_repository import GraphRepository
from app.ports.task_queue import GraphTaskQueue

logger = logging.getLogger(__name__)


class GraphTaskConsumer(BaseConsumer):
    """不停消费抽取任务：文档 → GraphContribution → Neo4j 整篇替换。"""

    consumer_name_prefix = "graph-consumer"

    def __init__(
        self,
        *,
        queue: GraphTaskQueue,
        session_factory: async_sessionmaker,
        extraction_service: GraphExtractionService,
        graph: GraphRepository,
        chunk_index: ChunkIndex,
        policy: TaskPolicy = GRAPH_TASK_POLICY,
        consumer_name: str | None = None,
    ) -> None:
        super().__init__(
            queue=queue,
            session_factory=session_factory,
            policy=policy,
            consumer_name=consumer_name,
        )
        self._extraction = extraction_service
        self._graph = graph
        self._index = chunk_index

    def _extract_task_ids(self, data: dict[str, Any]) -> dict[str, str] | None:
        task_id = data.get("task_id")
        document_id = data.get("document_id")
        if not task_id or not document_id:
            return None
        return {"task_id": task_id, "document_id": document_id}

    async def _handle_task(self, *, task_id: str, document_id: str) -> None:
        """取文档原文 → 抽取 → 写图 → 落任务状态。业务失败落库后正常返回。"""

        async with self._session_factory() as session:
            tasks = SqlAlchemyGraphTaskRepository(session, retry_backoff_seconds=self._backoff)

            task = await tasks.get(task_id)
            if task is None:
                # 文档被删，任务随 FK 级联消失：无事可做
                logger.warning("抽取任务不存在（已级联删除？）: task=%s", task_id)
                return
            if task.status in (GraphTaskStatus.SUCCESS, GraphTaskStatus.FAILED):
                return  # 幂等：redelivery

            documents = SqlAlchemyDocumentRepository(session)
            document = await documents.get(document_id)
            if document is None:
                await tasks.mark_success(task_id)  # 防御：行没了也算消费掉
                await session.commit()
                return

            chunks = await self._index.get_document_chunks(document_id=document_id)
            if not chunks:
                # 检索索引里没块（未索引/重建中）：没原料可抽，也不算失败
                await tasks.mark_success(task_id)
                await session.commit()
                return

            try:
                contribution = await self._extraction.build(document.name, chunks)
                await self._graph.upsert_document_graph(
                    document_id=document_id,
                    entities=contribution.entities,
                    triples=contribution.triples,
                )
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                await tasks.record_failure(task_id, error=error)
                entry = await tasks.get(task_id)
                if entry is not None and entry.attempts >= self._policy.max_attempts:
                    await tasks.mark_failed(task_id)
                    logger.error(
                        "抽取任务失败达到上限: task=%s doc=%s error=%s",
                        task_id,
                        document_id,
                        error,
                    )
                else:
                    logger.warning(
                        "抽取失败（未超限，回 PENDING 等重投）: task=%s doc=%s error=%s",
                        task_id,
                        document_id,
                        error,
                    )
                await session.commit()
                return

            await tasks.mark_success(task_id)
            await session.commit()
            logger.info(
                "图谱抽取完成: doc=%s entities=%d triples=%d",
                document_id,
                len(contribution.entities),
                len(contribution.triples),
            )


__all__ = ["GraphTaskConsumer"]
