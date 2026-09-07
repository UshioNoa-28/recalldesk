"""Eval 出题任务队列：独立 stream/group，与文档队列互不干扰。"""

from __future__ import annotations

import logging

from redis.asyncio import Redis

from app.infrastructure.queues.base import RedisStreamQueue
from app.ports.task_queue import EvalTaskQueue
from settings import settings

logger = logging.getLogger(__name__)


class RedisEvalTaskQueue(RedisStreamQueue, EvalTaskQueue):
    """Eval 出题任务的 Redis Stream 队列。"""

    def __init__(self, redis: Redis) -> None:
        super().__init__(
            redis,
            stream=settings.redis_eval_task_stream,
            group=settings.redis_eval_consumer_group,
            maxlen=settings.redis_stream_maxlen,
        )

    async def enqueue(self, *, task_id: str, item_id: str) -> str:
        message_id = await self._redis.xadd(
            name=self._stream,
            fields={
                "task_id": task_id,
                "item_id": item_id,
            },
            maxlen=self._maxlen,
            approximate=True,  # ~ 近似裁剪：快，允许长度略超 maxlen
        )
        logger.info(
            "任务已投递: stream=%s msg_id=%s task=%s item=%s",
            self._stream,
            message_id,
            task_id,
            item_id,
        )
        return message_id


__all__ = ["RedisEvalTaskQueue"]
