"""任务队列端口：文档索引与 Eval 出题各一个接口，应用层不碰 Redis 细节。

两个队列共享 Redis Stream 的消费能力（组管理 / 读取 / ACK / 认领孤儿消息），
只有 enqueue 的消息字段不同；拆成两个类型是为了让 DI 按类型区分注入，
避免把 eval 任务投到文档队列（或反过来）。
"""

from __future__ import annotations

from typing import Protocol


class _StreamQueue(Protocol):
    """Redis Stream 消费侧的共有能力，与具体任务类型无关。"""

    async def ensure_consumer_group(self) -> None:
        """确保消费者组存在（已存在则忽略）。"""
        ...

    async def read_new(
        self,
        *,
        consumer_name: str,
        count: int,
        block_ms: int,
    ) -> list[tuple[str, dict]]:
        """读取组内未分配的新消息，返回 [(message_id, fields), ...]。"""
        ...

    async def ack(self, message_id: str) -> None:
        """确认消息处理完成。"""
        ...

    async def claim_orphans(
        self,
        *,
        consumer_name: str,
        count: int,
    ) -> list[tuple[str, dict]]:
        """认领空闲超时的未确认消息（消费者崩溃遗留）。"""
        ...


class DocumentTaskQueue(_StreamQueue, Protocol):
    """文档索引任务队列（anna_rag_document_tasks）。"""

    async def enqueue(self, *, task_id: str, document_id: str, operation: str) -> str:
        """发布一条文档任务，返回消息 ID。"""
        ...


class EvalTaskQueue(_StreamQueue, Protocol):
    """Eval 出题任务队列（anna_rag_eval_tasks）。"""

    async def enqueue(self, *, task_id: str, item_id: str) -> str:
        """发布一条 eval 任务，返回消息 ID。"""
        ...


__all__ = ["DocumentTaskQueue", "EvalTaskQueue"]
