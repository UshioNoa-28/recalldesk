"""评测域模型：状态机 + 读模型 DTO（仓储返回、API 序列化的统一形状）。

eval_testsets 不存进度计数器：条目状态本身就是事实来源，
progress_done / progress_total 由 items 聚合算出（见 EvalRepository）。
eval_runs 同理，done 数的是 eval_run_items 里已经写了几行。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class TestSetStatus(StrEnum):
    """评测集生命周期。"""

    GENERATING = "generating"   # LLM 出题中
    READY = "ready"             # 出题完成，可跑评测
    FAILED = "failed"           # 出题失败


class EvalItemStatus(StrEnum):
    """评测集条目（题目）生成状态。"""

    PENDING = "pending"   # 创建快照，等待 LLM 出题
    READY = "ready"       # 出题完成，query 已写入
    FAILED = "failed"     # 出题重试超限


class EvalTaskStatus(StrEnum):
    """任务发件箱状态机：eval_tasks（出题）与 eval_run_tasks（逐题评测）共用。"""

    PENDING = "pending"   # 已创建，等待投递
    QUEUE = "queue"       # 已投递到 Redis Stream
    SUCCESS = "success"   # 消费成功
    FAILED = "failed"     # 重试超限，终态


class EvalRunStatus(StrEnum):
    """一次评测运行的生命周期。

    RUNNING 不再绑定某个进程：逐题是队列任务，进程崩了消息由 XAUTOCLAIM
    认领重投，run 自己会续上；只有「某题重试超限」这种真失败才会把它收尾成
    FAILED（EvalRepository.finalize_run）。
    """

    RUNNING = "running"   # 逐题检索中
    DONE = "done"         # 全部题目打分完成，metrics 已聚合
    FAILED = "failed"     # 中途异常 / 进程重启被打断


@dataclass
class EvalTestSet:
    id: str
    name: str
    status: TestSetStatus
    progress_done: int  # 已进入终态（ready 或 failed）的条目数
    progress_total: int
    error_message: str | None
    created_at: datetime


@dataclass(frozen=True)
class ChunkRef:
    """出题素材的坐标：某个文档的第几块。

    题目存的就是这个坐标，不复制原文：分块文本住在检索索引（现 Neo4j）里，
    而索引本身是"磁盘原文 + 重索引"的可重建派生物——两头都不是 PG，PG 不抄。
    出题时按坐标回查（ChunkIndex.get_chunk）。
    """

    document_id: str
    chunk_index: int


@dataclass
class EvalTestSetItem:
    """A test question: equal-rank evidence chunk coords + the generated query.

    Equal-rank era (2026-09-15 ruling): no "primary coordinate" in the evidence
    set -- ordinal is assembly order only; the service layer does no dedup, so
    the same chunk set may spawn as many questions as you like.
    Deleting a document purges every item referencing it (evidence RESTRICT is
    the loud fuse); cleanup lives in DocumentService.delete.
    """

    id: str
    status: EvalItemStatus = EvalItemStatus.PENDING
    query: str | None = None
    error_message: str | None = None
    evidence: list[ChunkRef] = field(default_factory=list)

    def evidence_refs(self) -> list[ChunkRef]:
        """出题与打分统一读的坐标全集（去重保序，拼装顺序即列表顺序）。"""

        return list(dict.fromkeys(self.evidence))


@dataclass
class EvalTask:
    """出题任务发件箱条目，与 DocumentTask 同形。"""

    id: str
    testset_id: str
    item_id: str
    status: EvalTaskStatus
    attempts: int
    last_error: str | None
    created_at: datetime
    queued_at: datetime | None


@dataclass
class EvalRunTask:
    """逐题评测任务发件箱条目：一次 run 开跑时按 ready 题 fan-out，一题一行。

    状态机复用 EvalTaskStatus；(run_id, item_id) 唯一，重试是复位重投
    而不是补发新行（出题侧 reset_for_retry 的同款理由）。
    """

    id: str
    run_id: str
    item_id: str
    status: EvalTaskStatus
    attempts: int
    last_error: str | None
    created_at: datetime
    queued_at: datetime | None


@dataclass
class EvalRunItem:
    """一道题在一次 run 里的结果。

    只存不可再生的事实（每块证据排在第几、该几块捞回几块、这条查询花了多久），
    joint_hit / average_precision / evidence_coverage 是这几列的纯函数，
    所以是属性而不是字段。
    已裁撤的口径（2026-09-15 裁决，聚合只留 recall@k / map@k / evidence_coverage）：
    mrr（ranks[0] 的倒数，被 map@k 替代）、文档级 recall 与 low_recall
    （被"块级全在"的 joint 口径兼并——joint@k 对外直接叫 Recall@k，
    文档级那个"找对篇挑错块也算对"的宽口径没有存在价值）。
    题面与坐标从 eval_testset_items 联查带出来：抄一份进结果表，题目被删改之后
    历史结果就会开始说谎。坐标一律走 evidence，没有主坐标（见 EvalTestSetItem）。
    """

    testset_item_id: str
    query: str | None
    hit_rank: int | None  # 最早命中那块的名次（1 起），None = 检索没捞回任何证据
    latency_ms: float
    evidence_total: int = 1  # 该题应有的证据块数（打分时快照）
    evidence_matched: int = 0  # top-k 内捞回了几块证据
    # 每块被捞回证据的名次（按命中升序）：map 的原料；0014 前的历史行为 None
    evidence_ranks: list[int] | None = None

    @property
    def joint_hit(self) -> int:
        """块级全在（对外口径：Recall@k，即 2WikiMQ 的 Joint Evidence）。"""

        return 1 if 0 < self.evidence_total <= self.evidence_matched else 0

    @property
    def average_precision(self) -> float | None:
        """MAP 的单题原料：Σ(第 i 块证据处 i/rank_i) / 应有块数。

        未命中的证据按 0 计入分母，名次越靠后 precision 被噪声稀释越狠——
        是唯一会惩罚"证据旁边挤垃圾"的指标。老行没存名次返回 None，
        聚合侧按 0 计（重跑 run 即刷新）。
        """

        if self.evidence_ranks is None:
            return None
        if self.evidence_total <= 0:
            return 0.0
        hits = sorted(self.evidence_ranks)
        return sum(
            (index + 1) / rank for index, rank in enumerate(hits[: self.evidence_total])
        ) / self.evidence_total

    @property
    def evidence_coverage(self) -> float:
        """部分分：捞回的证据块 / 应有证据块。与 joint_hit 不重复——
        joint 是全有全无（0/1），coverage 给多跳题"差一块"的中间态一个刻度。"""

        if self.evidence_total <= 0:
            return 0.0
        return min(1.0, self.evidence_matched / self.evidence_total)


@dataclass
class EvalRun:
    """一次运行：testset + 配置快照 + 聚合指标。不含逐题结果（另一次查询）。"""

    id: str
    testset_id: str
    status: EvalRunStatus
    config: dict[str, Any]
    metrics: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    finished_at: datetime | None
    progress_done: int  # 已写出结果的题数
    progress_total: int  # 测试集当前 ready 题数：跑完后被删题会让它小于 done


__all__ = [
    "ChunkRef",
    "EvalItemStatus",
    "EvalRun",
    "EvalRunItem",
    "EvalRunStatus",
    "EvalRunTask",
    "EvalTask",
    "EvalTaskStatus",
    "EvalTestSet",
    "EvalTestSetItem",
    "TestSetStatus",
]
