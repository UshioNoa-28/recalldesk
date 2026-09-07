"""发布者基类：轮询 PENDING 任务并投递到队列的通用后台循环。

DocumentTaskPublisher（文档索引）与 EvalTaskPublisher（出题）只差三处：
节奏参数来自各自的 settings、怎么领 PENDING、投失败后怎么收尾。
「轮询 + 异常兜底 + 可中断等待」这套循环是同一份，放在这里；
领与投留给子类实现。

先投递后标 QUEUE：若两步之间崩溃，任务保持 PENDING，下一轮重复投递，
消费者幂等消费，因此至少一次投递是安全的。
"""

from __future__ import annotations

import abc
import asyncio
import logging

from sqlalchemy.ext.asyncio import async_sessionmaker

logger = logging.getLogger(__name__)


class BasePublisher(abc.ABC):
    """不停读 PENDING -> 投递队列 -> 标 QUEUE 的后台循环。"""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker,
        interval_seconds: float,
        batch_size: int,
        max_attempts: int,
    ) -> None:
        self._session_factory = session_factory
        self._interval_seconds = interval_seconds
        self._batch_size = batch_size
        self._max_attempts = max_attempts

    async def run(self, stop_event: asyncio.Event) -> None:
        name = type(self).__name__
        logger.info(
            "启动 %s: interval=%.2fs batch=%d max_attempts=%d",
            name,
            self._interval_seconds,
            self._batch_size,
            self._max_attempts,
        )
        while not stop_event.is_set():
            try:
                published = await self.publish_pending_once()
                if published:
                    logger.info("%s 投递完成: %d 条", name, published)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("%s 轮询异常，下一轮重试", name)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self._interval_seconds)
            except TimeoutError:
                pass

    @abc.abstractmethod
    async def publish_pending_once(self) -> int:
        """读取一批 PENDING 并投递，返回成功数量。"""


__all__ = ["BasePublisher"]
