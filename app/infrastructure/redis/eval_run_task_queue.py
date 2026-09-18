"""Eval 逐题评测任务队列：独立 stream/group，与出题/文档队列互不干扰。"""

from __future__ import annotations

import logging

from redis.asyncio import Redis

from app.config import EVAL_RUN_TASK_POLICY, REDIS_BACKEND, RedisBackend, TaskPolicy
from app.infrastructure.redis.base import RedisStreamQueue
from app.ports.task_queue import EvalRunTaskQueue

logger = logging.getLogger(__name__)


class RedisEvalRunTaskQueue(RedisStreamQueue, EvalRunTaskQueue):
    """逐题评测任务的 Redis Stream 队列。"""

    def __init__(
        self,
        redis: Redis,
        *,
        policy: TaskPolicy = EVAL_RUN_TASK_POLICY,
        backend: RedisBackend = REDIS_BACKEND,
    ) -> None:
        super().__init__(
            redis,
            stream=policy.stream,
            group=policy.consumer_group,
            backend=backend,
        )

    async def enqueue(self, *, task_id: str, run_id: str, item_id: str) -> str:
        message_id = await self._redis.xadd(
            name=self._stream,
            fields={
                "task_id": task_id,
                "run_id": run_id,
                "item_id": item_id,
            },
            maxlen=self._maxlen,
            approximate=True,  # ~ 近似裁剪：快，允许长度略超 maxlen
        )
        logger.info(
            "任务已投递: stream=%s msg_id=%s task=%s run=%s item=%s",
            self._stream,
            message_id,
            task_id,
            run_id,
            item_id,
        )
        return message_id


__all__ = ["RedisEvalRunTaskQueue"]
