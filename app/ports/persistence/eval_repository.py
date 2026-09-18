"""评测仓储端口：测试集（eval_testsets）+ 题目（eval_testset_items）+ 运行
（eval_testset* / eval_tasks）。

纯数据访问：不 commit，事务由调用方（service / worker）控制。
任务队列侧的表各有端口（eval_tasks 在 EvalTaskRepository，
逐题评测任务 eval_run_tasks 在 EvalRunTaskRepository）；这里管业务事实：
题与出题任务；run 侧（建行/逐题结果/聚合收尾）在 EvalRunRepository。
"""

from __future__ import annotations

from typing import Protocol

from app.domain.eval import (
    ChunkRef,
    EvalTestSet,
    EvalTestSetItem,
)


class EvalRepository(Protocol):
    """评测集、题目与运行的持久化能力。"""

    # ---- testsets ----

    async def create_testset(self, *, testset_id: str, name: str) -> None:
        """创建评测集，初始状态 generating。"""
        ...

    async def get_testset(self, testset_id: str) -> EvalTestSet | None:
        """单条评测集元信息（不含 items，含派生进度）。"""
        ...

    async def list_testsets(self) -> list[EvalTestSet]:
        """评测集列表，按创建时间降序（含派生进度）。"""
        ...

    async def delete_testset(self, testset_id: str) -> None:
        """删除评测集（items / eval_tasks 级联）。"""
        ...

    async def finalize_testset(self, testset_id: str) -> None:
        """全部条目进入终态后流转测试集状态；未完成时是空操作。

        完成条件是「至少有一道题且没有 pending 条目」：建集与加题已经分开，
        空集是常态而不是坏数据，所以 0 条目留在 generating。永久失败的
        条目不会把测试集卡住。可被任意 worker 重复/并发调用：写是
        `WHERE status = 'generating'` 的条件写，不是读-改-写，
        因此幂等且不需要行锁。
        """
        ...

    async def reopen_testset(self, testset_id: str) -> None:
        """把测试集退回 generating 并清掉上次的 error_message。

        追加新题时必须调用：否则一个 ready 的集加了题还显示 ready。
        """
        ...

    # ---- items ----

    async def add_testset_items(
        self, testset_id: str, groups: list[list[ChunkRef]]
    ) -> list[str]:
        """批量写入题目并返回新题 id（与入参 groups 同序）。

        一组坐标出一道题，全组落进证据表（0013 起 items 无坐标列）；
        ordinal 只是拼装顺序，没有主坐标，证据允许跨题任意重复
        （2026-09-15 平权裁决：连完全相同的组也放行，查重已整体废除）。
        query 留空由 LLM worker 异步生成。
        """
        ...

    async def list_testset_items(self, testset_id: str) -> list[EvalTestSetItem]:
        """题目列表（按写入顺序），含证据坐标集合与生成状态。"""
        ...

    async def get_item(self, item_id: str) -> EvalTestSetItem | None:
        """按 ID 查单条题目（含证据坐标）：worker 手上只有 item_id。"""
        ...

    async def delete_items_referencing_document(self, document_id: str) -> int:
        """删掉把该文档当证据的任何题目（证据平权，ordinal 无主从语义），返回删除数。

        0013 起 items 不再对 documents 有外键：「文档消失 => 引用它的题消失」
        这条语义完全靠这里显式维护，删文档的应用层用例必须在同一事务里先调它。
        evidence→documents 是 RESTRICT 外键，忘调这里的话删文档行会撞
        IntegrityError（有声保险丝，绝不静默留僵尸题）。
        连带 eval_run_items 历史行与未发出的 eval_tasks 随题目 CASCADE 一起走。
        """
        ...

    async def set_item_result(self, item_id: str, *, query: str) -> None:
        """写入生成的问题，item 状态 pending -> ready。"""
        ...

    async def set_item_failed(self, item_id: str, *, error: str) -> None:
        """item 状态 -> failed，记录错误。"""
        ...

    async def set_item_pending_retry(self, item_id: str) -> None:
        """failed 的题重置回 pending：清空 query 与 error，等着重新出题。

        只由 retry_failed_items 用例调用（调用方已确认条目是 failed），
        配合 EvalTaskRepository.reset_for_retry 成对出现。
        """
        ...

__all__ = ["EvalRepository"]
