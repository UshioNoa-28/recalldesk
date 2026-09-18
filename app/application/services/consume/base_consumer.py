"""消费者基类：领孤儿 -> 读新消息 -> 分发处理 -> ACK 的通用后台循环。

DocumentTaskConsumer（索引）、EvalQuestionConsumer（出题）、EvalRunConsumer
（逐题评测）只差两处：消息负载里要校验哪些字段、任务本体怎么执行。
「循环 + 孤儿认领 + ACK 规则」这套语义是同一份，放在这里；
字段提取与处理留给子类实现。

ACK 规则：_handle_task 正常返回（业务成功或失败都已落库）就 ACK；
它抛异常（典型是 commit 本身失败）则不 ACK，消息留在 PEL 等 XAUTOCLAIM
认领重投 —— DB 状态没变，重跑靠子类自己的幂等守卫，是安全的。
"""

from __future__ import annotations

import abc
import asyncio
import logging
import os
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import TaskPolicy
from app.ports.task_queue import StreamQueue

logger = logging.getLogger(__name__)

# 读新消息短阻塞（2s）：stop_event 最多延迟这么久被看到；
# 孤儿认领每轮最多 2 条，防止崩溃恢复期一条消息喂饱一轮。
_READ_COUNT = 1
_READ_BLOCK_MS = 2000
_ORPHAN_CLAIM_COUNT = 2


class BaseConsumer(abc.ABC):
    """不停消费队列任务、执行并回写状态的后台循环。

    本服务独占一个进程/容器，业务调用直接阻塞事件循环即可，
    不需要丢线程池。
    """

    # 消费者名的前缀（容器编排排查用得到具体名）
    consumer_name_prefix: str = "consumer"

    def __init__(
        self,
        *,
        queue: StreamQueue,
        session_factory: async_sessionmaker,
        policy: TaskPolicy,
        consumer_name: str | None = None,
    ) -> None:
        self._queue = queue
        self._session_factory = session_factory
        self._policy = policy
        self._backoff = policy.retry_backoff_seconds
        self._consumer_name = consumer_name or f"{self.consumer_name_prefix}-{os.getpid()}"

    async def run(self, stop_event: asyncio.Event) -> None:
        name = type(self).__name__
        logger.info("启动 %s: consumer=%s", name, self._consumer_name)
        await self._queue.ensure_consumer_group()
        while not stop_event.is_set():
            try:
                await self._claim_and_process_orphans()
                messages = await self._queue.read_new(
                    consumer_name=self._consumer_name,
                    count=_READ_COUNT,
                    block_ms=_READ_BLOCK_MS,
                )
                for message_id, data in messages:
                    await self._process_single_message(message_id, data)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("%s 消费循环异常", name)
                await asyncio.sleep(1.0)

    async def _claim_and_process_orphans(self) -> None:
        """认领空闲超时的未确认消息（消费者崩溃遗留）。"""

        try:
            claimed = await self._queue.claim_orphans(
                consumer_name=self._consumer_name,
                count=_ORPHAN_CLAIM_COUNT,
            )
            for message_id, data in claimed:
                logger.warning("认领孤儿任务: id=%s data=%s", message_id, data)
                await self._process_single_message(message_id, data)
        except Exception:
            logger.warning("认领孤儿任务异常（非致命）", exc_info=True)

    async def _process_single_message(self, message_id: str, data: dict[str, Any]) -> None:
        """处理单条消息；commit 成功才 ACK，失败留给 XAUTOCLAIM。"""

        ids = self._extract_task_ids(data)
        if ids is None:
            logger.error(
                "消息缺少必要字段，直接 ACK: msg_id=%s fields=%s",
                message_id,
                list(data.keys()),
            )
            await self._queue.ack(message_id)
            return

        logger.info("%s 处理任务: msg_id=%s %s", type(self).__name__, message_id, ids)
        try:
            await self._handle_task(**ids)
        except Exception:
            # 事务提交失败等未预期异常：不 ACK，消息留在 PEL，
            # 由 XAUTOCLAIM 认领重试（DB 状态未变，幂等）。
            logger.exception("任务处理异常（不 ACK，等待认领）: %s", ids)
            return
        await self._queue.ack(message_id)

    @abc.abstractmethod
    def _extract_task_ids(self, data: dict[str, Any]) -> dict[str, str] | None:
        """从消息负载提取 _handle_task 的关键字参数；缺字段返回 None。"""

    @abc.abstractmethod
    async def _handle_task(self, **ids: str) -> None:
        """执行任务本体。

        业务失败须在方法内落库并正常返回（由基类 ACK）；
        只有 commit 失败才允许抛出（基类不 ACK，留给重投）。
        """


__all__ = ["BaseConsumer"]
