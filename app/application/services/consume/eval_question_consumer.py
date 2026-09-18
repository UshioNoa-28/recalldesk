"""出题任务消费者：从 Eval Stream 消费任务，调 LLM 生成问题并回写。

设计说明（消费循环 / ACK 规则见 BaseConsumer）：
- APP 作用域后台循环，注入 session_factory 自管短事务（每任务一个）；
- 只依赖 EvalTaskQueue 接口，不碰 Redis 细节；
- 出题用的原文不进 PG：条目只存坐标集合（主 + 证据），素材在处理时按坐标
  回查检索索引（分块文本只活在索引里，可由原文件重建），所以「任一证据块取不到」和
  「素材空白」都是终态失败 —— 重试变不出原文来；
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
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.services.consume.base_consumer import BaseConsumer
from app.application.services.evaluation.eval_question_generator import (
    EvalQuestionGenerator,
    QuestionFragment,
)
from app.config import EVAL_TASK_POLICY, TaskPolicy
from app.domain.eval import EvalItemStatus, EvalTask, EvalTaskStatus
from app.infrastructure.postgres.eval_repository import SqlAlchemyEvalRepository
from app.infrastructure.postgres.eval_task_repository import SqlAlchemyEvalTaskRepository
from app.ports.chunk_index import ChunkIndex
from app.ports.task_queue import EvalTaskQueue

logger = logging.getLogger(__name__)


class EvalQuestionConsumer(BaseConsumer):
    """不停消费出题任务，调 LLM 生成问题并回写状态。"""

    consumer_name_prefix = "eval-consumer"

    def __init__(
        self,
        *,
        queue: EvalTaskQueue,
        session_factory: async_sessionmaker,
        question_generator: EvalQuestionGenerator,
        chunk_index: ChunkIndex,
        consumer_name: str | None = None,
        policy: TaskPolicy = EVAL_TASK_POLICY,
    ) -> None:
        super().__init__(
            queue=queue,
            session_factory=session_factory,
            policy=policy,
            consumer_name=consumer_name,
        )
        self._question_generator = question_generator
        self._index = chunk_index

    def _extract_task_ids(self, data: dict[str, Any]) -> dict[str, str] | None:
        task_id = data.get("task_id")
        item_id = data.get("item_id")
        if not task_id or not item_id:
            return None
        return {"task_id": task_id, "item_id": item_id}

    async def _handle_task(self, *, task_id: str, item_id: str) -> None:
        """调 LLM 出题并回写 task / item / testset 状态。

        业务失败在本方法内落库并正常返回（由调用方 ACK）；
        只有 commit 失败才会抛出。
        """

        async with self._session_factory() as session:
            tasks = SqlAlchemyEvalTaskRepository(session, retry_backoff_seconds=self._backoff)
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

            refs = item.evidence_refs()
            chunks = await asyncio.gather(
                *(
                    self._index.get_chunk(
                        document_id=ref.document_id, chunk_index=ref.chunk_index
                    )
                    for ref in refs
                )
            )
            fragments: list[QuestionFragment] = []
            missing: list[str] = []
            for ref, chunk in zip(refs, chunks, strict=True):
                text = (chunk["text"] if chunk else "").strip()
                if not text:
                    label = chunk["document_name"] if chunk else ref.document_id
                    missing.append(f"《{label}》#{ref.chunk_index}")
                    continue
                fragments.append(
                    QuestionFragment(
                        document_id=ref.document_id,
                        chunk_index=ref.chunk_index,
                        document_name=chunk["document_name"],
                        text=text,
                    )
                )
            if missing:
                # 出题素材的唯一权威在向量库：任一证据块取不到（文档已删/重建），
                # 这道题的 ground truth 就缺了一角，重试也变不出原文来，所以是
                # 终态而不是可重试失败——半截素材出的题会毒害整个测试集。
                error = (
                    f"证据切片 {'、'.join(missing)} 取不到可出题的原文"
                    "（文档已删除或重建？）"
                )
                await self._fail_item(tasks=tasks, evals=evals, task=task, error=error)
                await session.commit()
                return

            try:
                query = await self._question_generator.generate(fragments=fragments)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                await tasks.record_failure(task.id, error=error)
                refreshed = await tasks.get(task.id)
                if refreshed is not None and refreshed.attempts >= self._policy.max_attempts:
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
