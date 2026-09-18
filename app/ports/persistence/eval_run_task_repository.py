"""逐题评测任务发件箱（eval_run_tasks）端口：run 的 publisher / worker 侧数据访问。

只管任务本身；run 状态与逐题结果的读写在 EvalRepository。
与 EvalTaskRepository（出题任务）同形：一次 run 开跑 fan-out 一题一行，
重试是复位这一行而不是补发新行。
"""

from __future__ import annotations

from typing import Protocol

from app.domain.eval import EvalRunTask


class EvalRunTaskRepository(Protocol):
    """eval_run_tasks 任务生命周期。

    list_pending 使用 FOR UPDATE SKIP LOCKED，支持多个 publisher 并发领取；
    收外部传入的 session，不做 commit。
    """

    async def add(self, *, run_id: str, item_id: str) -> None:
        """向当前事务追加一条 PENDING 任务（一个 run 内每题唯一）。"""
        ...

    async def get(self, task_id: str) -> EvalRunTask | None:
        """按 ID 查任务。"""
        ...

    async def list_pending(self, *, limit: int) -> list[EvalRunTask]:
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

    async def reset_failed_for_run(self, run_id: str) -> int:
        """把该 run 里终态 FAILED 的任务复位回 PENDING（重试三件套清零），返回条数。"""
        ...

    async def count_by_status(self, run_id: str) -> dict[str, int]:
        """某 run 的任务按状态计数：finalize_run 判断「还有没有在途任务」用。"""
        ...


__all__ = ["EvalRunTaskRepository"]
