"""Redis Stream 任务队列基类。

XREADGROUP / XACK / XAUTOCLAIM 等消费侧细节都关在这里；
enqueue 由子类显式实现（各自的字段与日志），基类只提供公共配置。
"""

from __future__ import annotations

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from settings import settings


class RedisStreamQueue:
    """一组 (stream, group) 上的 Redis Stream 消费能力与公共配置。"""

    def __init__(
        self,
        redis: Redis,
        *,
        stream: str,
        group: str,
        maxlen: int,
    ) -> None:
        self._redis = redis
        self._stream = stream
        self._group = group
        self._maxlen = maxlen

    async def ensure_consumer_group(self) -> None:
        try:
            await self._redis.xgroup_create(
                name=self._stream,
                groupname=self._group,
                id="0",
                mkstream=True,
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def read_new(
        self,
        *,
        consumer_name: str,
        count: int,
        block_ms: int,
    ) -> list[tuple[str, dict]]:
        entries = await self._redis.xreadgroup(
            groupname=self._group,
            consumername=consumer_name,
            streams={self._stream: ">"},
            count=count,
            block=block_ms,
        )
        messages: list[tuple[str, dict]] = []
        for _stream_name, stream_messages in entries:
            for message_id, fields in stream_messages:
                messages.append((message_id, dict(fields)))
        return messages

    async def ack(self, message_id: str) -> None:
        await self._redis.xack(self._stream, self._group, message_id)

    async def claim_orphans(
        self,
        *,
        consumer_name: str,
        count: int,
    ) -> list[tuple[str, dict]]:
        res = await self._redis.xautoclaim(
            name=self._stream,
            groupname=self._group,
            consumername=consumer_name,
            min_idle_time=settings.redis_claim_min_idle_ms,  # 只认领空闲超时的消息
            start_id=settings.redis_claim_start_id,          # 从 PEL 的哪个位置开始扫
            count=count,                                     # 单次最多认领几条
        )
        claimed = res[1] if len(res) > 1 else []
        return [(message_id, dict(fields)) for message_id, fields in claimed]


__all__ = ["RedisStreamQueue"]
