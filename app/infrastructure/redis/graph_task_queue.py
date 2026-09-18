"""图谱抽取任务队列：独立 stream/group，与索引/评测队列互不干扰。"""

from __future__ import annotations

import logging

from redis.asyncio import Redis

from app.config import GRAPH_TASK_POLICY, REDIS_BACKEND, RedisBackend, TaskPolicy
from app.infrastructure.redis.base import RedisStreamQueue
from app.ports.task_queue import GraphTaskQueue

logger = logging.getLogger(__name__)


class RedisGraphTaskQueue(RedisStreamQueue, GraphTaskQueue):
    """graph_tasks 的 Redis Stream 队列。"""

    def __init__(
        self,
        redis: Redis,
        *,
        policy: TaskPolicy = GRAPH_TASK_POLICY,
        backend: RedisBackend = REDIS_BACKEND,
    ) -> None:
        super().__init__(
            redis,
            stream=policy.stream,
            group=policy.consumer_group,
            backend=backend,
        )

    async def enqueue(self, *, task_id: str, document_id: str) -> str:
        message_id = await self._redis.xadd(
            name=self._stream,
            fields={
                "task_id": task_id,
                "document_id": document_id,
            },
            maxlen=self._maxlen,
            approximate=True,
        )
        logger.info(
            "抽取任务已投递: stream=%s msg_id=%s task=%s doc=%s",
            self._stream,
            message_id,
            task_id,
            document_id,
        )
        return message_id


__all__ = ["RedisGraphTaskQueue"]
