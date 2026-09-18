"""出题任务发件箱（eval_tasks）端口：publisher / worker 侧的数据访问。

只管任务本身；题目（items）和测试集状态的读写在 EvalRepository。
"""

from __future__ import annotations

from typing import Protocol

from app.domain.eval import EvalTask


class EvalTaskRepository(Protocol):
    """eval_tasks 任务生命周期。

    与 DocumentTaskRepository 同形；list_pending 使用 FOR UPDATE SKIP LOCKED，
    支持多个 publisher 并发领取。收外部传入的 session，不做 commit。
    """

    async def add(self, *, testset_id: str, item_id: str) -> None:
        """向当前事务追加一条 PENDING 任务（每个 item 唯一）。"""
        ...

    async def get(self, task_id: str) -> EvalTask | None:
        """按 ID 查任务。"""
        ...

    async def list_pending(self, *, limit: int) -> list[EvalTask]:
        """领取一批 PENDING 任务（SKIP LOCKED），按创建时间升序。"""
        ...

    async def mark_queued(self, task_id: str) -> None:
        """标记任务已投递到 Redis Stream（PENDING -> QUEUE，记 queued_at）。"""
        ...

    async def mark_success(self, task_id: str) -> None:
        """标记任务消费成功（QUEUE -> SUCCESS）。"""
        ...

    async def record_failure(self, task_id: str, *, error: str) -> None:
        """记录一次失败：attempts+1、状态回 PENDING（指数退避等重投），
        超限终态由调用方随后用 mark_failed 覆盖。"""
        ...

    async def mark_failed(self, task_id: str) -> None:
        """把任务标记为终态 FAILED。"""
        ...

    async def reset_for_retry(self, *, item_id: str) -> None:
        """把 FAILED 的出题任务重置回 PENDING（清 attempts / 退避 / 错误），
        等 publisher 重新投递。

        item_id 一个任务（唯一约束），所以重试是复位而不是补发新行。
        没有 FAILED 任务可复位时抛 KeyError（条目与任务同事务进终态，
        出现不匹配说明数据坏了，宁可炸出来）。
        """
        ...


__all__ = ["EvalTaskRepository"]
