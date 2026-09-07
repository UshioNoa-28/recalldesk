"""Redis Stream 队列适配器测试：验证基类把接口方法翻译成正确的 Redis 命令，
以及 Document / Eval 两个子类各自投递到独立的 stream / group。"""

from __future__ import annotations

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from redis.exceptions import ResponseError

from app.infrastructure.queues import RedisDocumentTaskQueue, RedisEvalTaskQueue
from settings import settings


class RedisStreamQueueBaseTests(IsolatedAsyncioTestCase):
    """基类的消费侧行为，借用 RedisDocumentTaskQueue 验证。"""

    def setUp(self) -> None:
        self.redis = AsyncMock()
        self.queue = RedisDocumentTaskQueue(self.redis)

    async def test_ensure_consumer_group_creates_group(self) -> None:
        await self.queue.ensure_consumer_group()

        self.redis.xgroup_create.assert_awaited_once_with(
            name=settings.redis_document_task_stream,
            groupname=settings.redis_document_consumer_group,
            id="0",
            mkstream=True,
        )

    async def test_ensure_consumer_group_ignores_busygroup(self) -> None:
        self.redis.xgroup_create.side_effect = ResponseError(
            "BUSYGROUP consumer group name already exists"
        )

        await self.queue.ensure_consumer_group()  # 不应抛异常

    async def test_ensure_consumer_group_raises_other_errors(self) -> None:
        self.redis.xgroup_create.side_effect = ResponseError("NOGROUP something wrong")

        with self.assertRaises(ResponseError):
            await self.queue.ensure_consumer_group()

    async def test_read_new_flattens_xreadgroup_result(self) -> None:
        self.redis.xreadgroup.return_value = [
            (
                settings.redis_document_task_stream,
                [("1-0", {"task_id": "task-1", "document_id": "doc-1"})],
            )
        ]

        messages = await self.queue.read_new(consumer_name="consumer-1", count=1, block_ms=2000)

        self.assertEqual([("1-0", {"task_id": "task-1", "document_id": "doc-1"})], messages)

    async def test_ack_sends_xack(self) -> None:
        await self.queue.ack("1-0")

        self.redis.xack.assert_awaited_once_with(
            settings.redis_document_task_stream,
            settings.redis_document_consumer_group,
            "1-0",
        )

    async def test_claim_orphans_returns_claimed_messages(self) -> None:
        self.redis.xautoclaim.return_value = [
            "0-0",
            [("9-9", {"task_id": "task-9", "document_id": "doc-9"})],
            [],
        ]

        claimed = await self.queue.claim_orphans(consumer_name="consumer-2", count=2)

        self.assertEqual([("9-9", {"task_id": "task-9", "document_id": "doc-9"})], claimed)
        self.redis.xautoclaim.assert_awaited_once_with(
            name=settings.redis_document_task_stream,
            groupname=settings.redis_document_consumer_group,
            consumername="consumer-2",
            min_idle_time=settings.redis_claim_min_idle_ms,
            start_id=settings.redis_claim_start_id,
            count=2,
        )


class RedisDocumentTaskQueueTests(IsolatedAsyncioTestCase):
    async def test_enqueue_sends_document_fields_to_document_stream(self) -> None:
        redis = AsyncMock()
        redis.xadd.return_value = "1-0"
        queue = RedisDocumentTaskQueue(redis)

        message_id = await queue.enqueue(
            task_id="task-1",
            document_id="doc-1",
            operation="index",
        )

        self.assertEqual("1-0", message_id)
        redis.xadd.assert_awaited_once_with(
            name=settings.redis_document_task_stream,
            fields={"task_id": "task-1", "document_id": "doc-1", "operation": "index"},
            maxlen=settings.redis_stream_maxlen,
            approximate=True,
        )


class RedisEvalTaskQueueTests(IsolatedAsyncioTestCase):
    async def test_enqueue_sends_eval_fields_to_eval_stream(self) -> None:
        redis = AsyncMock()
        redis.xadd.return_value = "2-0"
        queue = RedisEvalTaskQueue(redis)

        message_id = await queue.enqueue(
            task_id="task-2",
            item_id="item-1",
        )

        self.assertEqual("2-0", message_id)
        redis.xadd.assert_awaited_once_with(
            name=settings.redis_eval_task_stream,
            fields={"task_id": "task-2", "item_id": "item-1"},
            maxlen=settings.redis_stream_maxlen,
            approximate=True,
        )

    async def test_ack_targets_eval_stream_and_group(self) -> None:
        redis = AsyncMock()
        queue = RedisEvalTaskQueue(redis)

        await queue.ack("2-0")

        redis.xack.assert_awaited_once_with(
            settings.redis_eval_task_stream,
            settings.redis_eval_consumer_group,
            "2-0",
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
