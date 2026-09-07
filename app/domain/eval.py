"""评测域模型：状态机 + 读模型 DTO（仓储返回、API 序列化的统一形状）。

eval_testsets 不存进度计数器：条目状态本身就是事实来源，
progress_done / progress_total 由 items 聚合算出（见 EvalRepository）。
eval_runs 同理，done 数的是 eval_run_items 里已经写了几行。
"""

from __future__ import annotations

from dataclasses import dataclass
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
    """eval_tasks（出题任务发件箱）状态机，与 document_tasks 同形。"""

    PENDING = "pending"   # 已创建，等待投递
    QUEUE = "queue"       # 已投递到 Redis Stream
    SUCCESS = "success"   # 消费成功
    FAILED = "failed"     # 重试超限，终态


class EvalRunStatus(StrEnum):
    """一次评测运行的生命周期。

    RUNNING 是被启动扫（EvalRepository.fail_stale_runs）认领的那个状态：进程崩在
    半路，行会留在 running，下次启动统一标成 failed。
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

    题目存的就是这个坐标，不复制原文：分块文本的唯一权威在 Qdrant，
    点 id 由坐标算出，出题时回查（VectorRepository.get_chunk）。
    """

    document_id: str
    chunk_index: int


@dataclass
class EvalTestSetItem:
    """一道题：出题素材的坐标 + LLM 生成的问题。

    没有原文字段，所以 answer_document_id 是真外键：文档被删则它的点一起
    消失，题目再没有可命中的 ground truth，级联删掉比留着强。
    """

    id: str
    answer_document_id: str
    answer_chunk_index: int
    status: EvalItemStatus = EvalItemStatus.PENDING
    query: str | None = None
    error_message: str | None = None


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
class EvalRunItem:
    """一道题在一次 run 里的结果。

    只存不可再生的事实（期望切片排在第几、期望文档有没有进 top-k、这条查询花了
    多久），mrr 与 low_recall 都是这几列的纯函数，所以是属性而不是字段。
    题面与坐标从 eval_testset_items 联查带出来：抄一份进结果表，题目被删改之后
    历史结果就会开始说谎。
    """

    testset_item_id: str
    query: str | None
    answer_document_id: str
    answer_chunk_index: int
    hit_rank: int | None  # 期望切片的首次命中名次（1 起），None = 检索没返回它
    recall: int  # 期望文档是否进了 top-k：0/1，文档级，比 hit_rank 粗
    latency_ms: float

    @property
    def mrr(self) -> float:
        return 1.0 / self.hit_rank if self.hit_rank else 0.0

    @property
    def low_recall(self) -> bool:
        return self.recall == 0


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
    "EvalTask",
    "EvalTaskStatus",
    "EvalTestSet",
    "EvalTestSetItem",
    "TestSetStatus",
]
