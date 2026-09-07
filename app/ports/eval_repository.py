"""评测仓储端口：测试集（eval_testsets）+ 题目（eval_testset_items）+ 运行
（eval_runs / eval_run_items）。

纯数据访问：不 commit，事务由调用方（service / worker）控制。
出题任务（eval_tasks）的生命周期在 EvalTaskRepository，那是队列的事，
不属于测试集这个聚合；run 是题出好之后的检索评测，不碰队列，所以在这里。
"""

from __future__ import annotations

from typing import Any, Protocol

from app.domain.eval import (
    ChunkRef,
    EvalRun,
    EvalRunItem,
    EvalRunStatus,
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
        self, testset_id: str, refs: list[ChunkRef]
    ) -> None:
        """批量写入题目坐标，query 留空由 LLM worker 异步生成。

        只存坐标不存原文，所以 (testset_id, answer_document_id,
        answer_chunk_index) 唯一约束会挡住重复出题，调用方要先去重。
        """
        ...

    async def list_testset_items(self, testset_id: str) -> list[EvalTestSetItem]:
        """题目列表（按写入顺序），含坐标与生成状态。"""
        ...

    async def get_item(self, item_id: str) -> EvalTestSetItem | None:
        """按 ID 查单条题目：worker 手上只有 item_id。"""
        ...

    async def set_item_result(self, item_id: str, *, query: str) -> None:
        """写入生成的问题，item 状态 pending -> ready。"""
        ...

    async def set_item_failed(self, item_id: str, *, error: str) -> None:
        """item 状态 -> failed，记录错误。"""
        ...

    # ---- runs ----

    async def create_run(
        self, *, run_id: str, testset_id: str, config: dict[str, Any]
    ) -> None:
        """创建一次运行，初始状态 running，config 是当时的检索配置快照。"""
        ...

    async def record_run_item(self, run_id: str, result: EvalRunItem) -> None:
        """写入一题的结果。

        一次一题而不是批量：跑完一题就提交一题，轮询详情才看得到进度，
        中途挂掉也只丢当前这一题。(run_id, testset_item_id) 唯一，重复写会撞约束。
        """
        ...

    async def finish_run(
        self,
        run_id: str,
        *,
        status: EvalRunStatus,
        metrics: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> None:
        """结束运行：写聚合指标与 finished_at。

        条件写 `WHERE status = 'running'`：只有还活着的 run 能被收尾，所以
        重复调用（以及和启动扫相撞）都是空操作，不会把已终态的 run 改回去。
        """
        ...

    async def get_run(self, run_id: str) -> EvalRun | None:
        """运行详情（含派生进度，不含逐题结果）。"""
        ...

    async def list_run_items(self, run_id: str) -> list[EvalRunItem]:
        """逐题结果，题面与坐标联查带出。

        走 inner join：题目被级联删（它指向的文档没了）则它的结果也不再
        指向任何可复核的东西，跟着一起消失比留下对不上号的行诚实。
        """
        ...

    async def list_runs(self, testset_id: str) -> list[EvalRun]:
        """某测试集的历史运行（含进度，不含逐题结果），按创建时间降序。"""
        ...

    async def list_unscored_questions(self, run_id: str) -> list[EvalTestSetItem]:
        """这次运行还没打分的题目（测试集里 status=ready 的那些）。

        执行器的工作清单从这里来，所以重入同一个 run 不会重复问一遍：
        已经有结果的题不再出现。
        """
        ...

    async def fail_stale_runs(self, *, error: str) -> int:
        """把所有还挂在 running 的运行标成 failed，返回影响行数。

        启动时调用一次：run 是进程内后台任务，进程活着才会往前走，所以启动时
        看到的 running 一定是上次遗留的。没有租约/心跳可判，宁可一律打断。
        """
        ...


__all__ = ["EvalRepository"]
