"""graph_tasks 发件箱端口：文档→图谱抽取任务（第四条 outbox 链路）。

与 document/eval 两条链路口径一致：纯数据访问、不 commit，
事务边界归调用方；退避公式在实现内但基数走构造参数。
"""

from __future__ import annotations

from typing import Protocol

from app.domain.graph import GraphTask


class GraphTaskRepository(Protocol):
    """graph_tasks 表读写。"""

    async def add(self, *, document_id: str) -> None:
        """插入一条 PENDING 抽取任务（同事务随业务写，不在仓储内提交）。"""
        ...

    async def get(self, entry_id: str) -> GraphTask | None:
        """按 ID 查任务。"""
        ...

    async def list_pending(self, *, limit: int) -> list[GraphTask]:
        """领取已到重试时间的 PENDING（FOR UPDATE SKIP LOCKED）。"""
        ...

    async def mark_queued(self, entry_id: str) -> None:
        """PENDING -> QUEUE。"""
        ...

    async def mark_success(self, entry_id: str) -> None:
        """QUEUE -> SUCCESS。"""
        ...

    async def record_failure(self, entry_id: str, *, error: str) -> None:
        """attempts+1、回 PENDING、指数退避；超限终态由调用方 mark_failed。"""
        ...

    async def mark_failed(self, entry_id: str) -> None:
        """标记终态 FAILED。"""
        ...

    async def latest_for_document_ids(
        self, document_ids: list[str]
    ) -> dict[str, tuple[str, str | None]]:
        """每篇文档最新一条抽取任务：{document_id: (status, last_error)}。

        没有任何任务的文档不出现在结果里（服务层把缺失读成"从未抽取"）。
        """
        ...

    async def queue_extraction(self, document_id: str) -> str:
        """手动重抽：failed/success 复位最新行为 PENDING（整篇替换幂等），
        无历史则新建。在途（pending/queue）时抛 ValueError，防止排队套排队。

        返回 "requeued" | "created"，供接口回显。
        """
        ...


__all__ = ["GraphTaskRepository"]
