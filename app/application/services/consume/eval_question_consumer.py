"""出题任务消费者：从 Eval Stream 消费任务，调 LLM 生成问题并回写。

设计说明：
- APP 作用域后台循环，注入 session_factory 自管短事务（每任务一个）；
- 只依赖 EvalTaskQueue 接口，不碰 Redis 细节；
- 出题用的原文不进 PG：条目只存坐标，素材在处理时按坐标回查向量库
  （Qdrant 是分块文本的唯一权威），所以「取不到素材」和「素材空白」都是
  终态失败 —— 重试变不出原文来；
- ACK 规则：commit 成功就 ACK（业务成功或失败落库都是），只有 commit
  本身失败才不 ACK，留给 XAUTOCLAIM 恢复；
- 幂等守卫：redelivery 时任务已是终态（或 item 已 ready）直接跳过，
  不重复调 LLM；
- LLM 失败：attempts+1、任务回 PENDING（指数退避，由 EvalTaskPublisher
  重新投递），超限任务和 item 一起标 FAILED；
- 任何把 item 推到终态的路径都走 _fail_item：任务失败 + 条目失败 + 一次
  finalize_testset 绑在一起，失败条目也不例外，否则测试集会永远停在 generating。
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.services.eval_question_generator import EvalQuestionGenerator
from app.domain.eval import EvalItemStatus, EvalTask, EvalTaskStatus
from app.infrastructure.eval_repository import SqlAlchemyEvalRepository
from app.infrastructure.eval_task_repository import SqlAlchemyEvalTaskRepository
from app.ports.task_queue import EvalTaskQueue
from app.ports.vector_repository import VectorRepository
from settings import settings

logger = logging.getLogger(__name__)


class EvalQuestionConsumer:
    """不停消费出题任务，调 LLM 生成问题并回写状态。"""

    def __init__(
        self,
        *,
        queue: EvalTaskQueue,
        session_factory: async_sessionmaker,
        question_generator: EvalQuestionGenerator,
        vector_repository: VectorRepository,
        consumer_name: str | None = None,
    ) -> None:
        self._queue = queue
        self._session_factory = session_factory
        self._question_generator = question_generator
        self._vectors = vector_repository
        self._consumer_name = consumer_name or f"eval-consumer-{os.getpid()}"
        self._stop_event = asyncio.Event()

    async def run(self, stop_event: asyncio.Event) -> None:
        logger.info("启动 EvalQuestionConsumer: consumer=%s", self._consumer_name)
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
                logger.exception("EvalQuestionConsumer 消费循环异常")
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
        item_id = data.get("item_id")
        if not task_id or not item_id:
            logger.error("消息缺少 task_id/item_id，直接 ACK: msg_id=%s", message_id)
            await self._queue.ack(message_id)
            return

        logger.info("处理出题任务: msg_id=%s task=%s item=%s", message_id, task_id, item_id)
        try:
            await self._handle_task(task_id=task_id, item_id=item_id)
        except Exception:
            # 事务提交失败等未预期异常：不 ACK，消息留在 PEL，
            # 由 XAUTOCLAIM 认领重试（DB 状态未变，幂等）。
            logger.exception("出题任务处理异常（不 ACK，等待认领）: task=%s", task_id)
            return
        await self._queue.ack(message_id)

    async def _handle_task(self, *, task_id: str, item_id: str) -> None:
        """调 LLM 出题并回写 task / item / testset 状态。

        业务失败在本方法内落库并正常返回（由调用方 ACK）；
        只有 commit 失败才会抛出。
        """

        async with self._session_factory() as session:
            tasks = SqlAlchemyEvalTaskRepository(session)
            evals = SqlAlchemyEvalRepository(session)

            task = await tasks.get(task_id)
            if task is None:
                # 测试集/条目已删除，任务被级联清理：无事可做
                logger.warning("出题任务不存在（已级联删除？）: task=%s", task_id)
                return
            if task.status in (EvalTaskStatus.SUCCESS, EvalTaskStatus.FAILED):
                return  # 幂等：redelivery，不重复调 LLM

            item = await evals.get_item(task.item_id)
            if item is None:
                await tasks.mark_failed(task.id)
                await session.commit()
                return
            if item.status == EvalItemStatus.READY:
                # 题已生成过（redelivery）：补记成功，收尾规则统一——
                # 观察到条目终态就试一次 finalize，它本身是幂等的。
                await tasks.mark_success(task.id)
                await evals.finalize_testset(task.testset_id)
                await session.commit()
                return

            chunk = await self._vectors.get_chunk(
                document_id=item.answer_document_id,
                chunk_index=item.answer_chunk_index,
            )
            context_text = (chunk["text"] if chunk else "").strip()
            if not context_text:
                # 出题素材的唯一权威在向量库：点取不到（文档已删/重建）或本身空白，
                # 重试也变不出原文来，所以是终态而不是可重试失败。
                error = (
                    f"切片 #{item.answer_chunk_index} 取不到可出题的原文"
                    "（文档已删除或重建？）"
                )
                await self._fail_item(tasks=tasks, evals=evals, task=task, error=error)
                await session.commit()
                return

            try:
                query = await self._question_generator.generate(
                    context_text=context_text,
                    document_name=chunk["document_name"],
                )
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                await tasks.record_failure(task.id, error=error)
                refreshed = await tasks.get(task.id)
                if refreshed is not None and refreshed.attempts >= settings.eval_task_max_attempts:
                    await self._fail_item(
                        tasks=tasks, evals=evals, task=task, error=error
                    )
                    logger.error(
                        "出题失败达到上限: task=%s item=%s error=%s", task.id, item.id, error
                    )
                else:
                    logger.warning("出题失败: task=%s error=%s", task.id, error)
                await session.commit()
                return

            await evals.set_item_result(item.id, query=query)
            await tasks.mark_success(task.id)
            await evals.finalize_testset(task.testset_id)
            await session.commit()

    async def _fail_item(
        self,
        *,
        tasks: SqlAlchemyEvalTaskRepository,
        evals: SqlAlchemyEvalRepository,
        task: EvalTask,
        error: str,
    ) -> None:
        """把条目推到终态：任务失败 + 条目失败 + 测试集收尾，缺一不可。

        少一次 finalize，测试集就会永远停在 generating。
        """

        await tasks.mark_failed(task.id)
        await evals.set_item_failed(task.item_id, error=error)
        await evals.finalize_testset(task.testset_id)


__all__ = ["EvalQuestionConsumer"]
