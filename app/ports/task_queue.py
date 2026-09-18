"""任务队列端口：文档索引 / Eval 出题 / Eval 逐题评测各一个接口，应用层不碰 Redis 细节。

三类队列共享 Redis Stream 的消费能力（组管理 / 读取 / ACK / 认领孤儿消息），
只有 enqueue 的消息字段不同；拆成多个类型是为了让 DI 按类型区分注入，
避免把一类任务投到另一类的队列。
"""

from __future__ import annotations

from typing import Protocol


class StreamQueue(Protocol):
    """Redis Stream 消费侧的共有能力，与具体任务类型无关（BaseConsumer 依赖它）。"""

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


class DocumentTaskQueue(StreamQueue, Protocol):
    """文档索引任务队列（anna_rag_document_tasks）。"""

    async def enqueue(self, *, task_id: str, document_id: str, operation: str) -> str:
        """发布一条文档任务，返回消息 ID。"""
        ...


class EvalTaskQueue(StreamQueue, Protocol):
    """Eval 出题任务队列（anna_rag_eval_tasks）。"""

    async def enqueue(self, *, task_id: str, item_id: str) -> str:
        """发布一条 eval 任务，返回消息 ID。"""
        ...


class EvalRunTaskQueue(StreamQueue, Protocol):
    """Eval 逐题评测任务队列（anna_rag_eval_run_tasks）。

    消息带 run_id + item_id：消费者手上只有坐标，题目与 run 配置现查。
    """

    async def enqueue(self, *, task_id: str, run_id: str, item_id: str) -> str:
        """发布一条逐题评测任务，返回消息 ID。"""
        ...


class GraphTaskQueue(StreamQueue, Protocol):
    """图谱抽取任务队列（anna_rag_graph_tasks）。"""

    async def enqueue(self, *, task_id: str, document_id: str) -> str:
        """发布一条抽取任务，返回消息 ID。"""
        ...


__all__ = [
    "DocumentTaskQueue",
    "EvalRunTaskQueue",
    "EvalTaskQueue",
    "GraphTaskQueue",
    "StreamQueue",
]
