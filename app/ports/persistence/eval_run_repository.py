"""评测 run 存储端口（现由 Postgres 实现）：run 与逐题结果。

与 EvalRepository（testsets/items）分家：run 侧只关心一次执行的建行、逐题
回写、聚合成指标与重开；题面/坐标靠 join 现有表，不复制。
"""

from __future__ import annotations

from typing import Any, Protocol

from app.domain.eval import (
    EvalRun,
    EvalRunItem,
    EvalRunStatus,
    EvalTestSetItem,
)


class EvalRunRepository(Protocol):
    """一次评测 run 的持久化：建行、逐题结果、聚合收尾、重开。"""

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

        run 任务的补发/对账从这个清单来：已经有结果的题不再出现，
        所以重入同一个 run 不会重复问一遍。
        """
        ...

    async def has_run_result(self, run_id: str, testset_item_id: str) -> bool:
        """这题在本次 run 里结没结果：消费者的 redelivery 幂等守卫。"""
        ...

    async def finalize_run(
        self, run_id: str, *, pending_open: int, failed: int
    ) -> None:
        """任务全部落定后把 run 收尾；还有在途任务（pending_open>0）时空操作。

        由调用方（consumer）先数好 eval_run_tasks 的状态再传进来：任务表归
        EvalRunTaskRepository 这个聚合，run 状态归这里，跨聚合不互相查表
        （与出题侧「数 items 的是 finalize_testset、数 tasks 的是 consumer」一致）。

        无在途且 failed==0 → 从库里的结果行聚合成 DONE（口径与逐题结果永远一致）；
        无在途但有 failed → 记 FAILED 并写明几题失败。收尾是条件写
        （WHERE status='running'），可被并发/重复调用，最后一个提交者才改得动终态。
        """
        ...


    async def reopen_run(self, run_id: str) -> None:
        """failed 的 run 重跑前翻回 running：清 error/finished_at。

        条件写 WHERE status='failed'——已 running/已 done 都是空操作；
        「一个测试集最多一个 running」的部分唯一索引仍然兜并发。
        """
        ...


__all__ = ["EvalRunRepository"]
