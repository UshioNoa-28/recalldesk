"""注入用的分组配置值对象。

纪律：`settings`（env 解析的大杂烩 god-object）只被组合根 container 读一次，
在 container 里切片成下面这些内聚的 frozen dataclass 再注入出去。下游模块
（仓储 / 队列 / publisher / consumer / 控制器）拿到的是**明确的类型和字段**，
不再 `from settings import settings` 满天飞。

这里的 DEFAULT_* 常量是各链路的出厂默认（与 settings 默认同源），
container 会用 settings 的实际值覆盖它们；测试直接引用这些常量即可，
不必为了构造一个真实对象而去依赖全局 settings。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskPolicy:
    """一条异步任务链路的完整策略：队列寻址 + 投递节奏 + 重试/退避。

    一份对象同时喂给该链路的 queue / publisher / consumer / 出箱仓储，
    省得三处各自读 settings 的同名旋钮、彼此漂移。
    """

    stream: str
    consumer_group: str
    publish_interval_seconds: float
    publish_batch_size: int
    max_attempts: int
    retry_backoff_seconds: float


@dataclass(frozen=True)
class RedisBackend:
    """所有 Stream 队列共享的底层参数（与具体任务类型无关）。"""

    maxlen: int
    claim_min_idle_ms: int
    claim_start_id: str


@dataclass(frozen=True)
class UploadLimits:
    """上传接口的约束：大小与允许的扩展名（已归一为带点小写集合）。"""

    max_bytes: int
    allowed_suffixes: frozenset[str]


DOCUMENT_TASK_POLICY = TaskPolicy(
    stream="anna_rag_document_tasks",
    consumer_group="anna_rag_document_workers",
    publish_interval_seconds=0.5,
    publish_batch_size=50,
    max_attempts=10,
    retry_backoff_seconds=30.0,
)

EVAL_TASK_POLICY = TaskPolicy(
    stream="anna_rag_eval_tasks",
    consumer_group="anna_rag_eval_workers",
    publish_interval_seconds=2.0,
    publish_batch_size=20,
    max_attempts=5,
    retry_backoff_seconds=30.0,
)

EVAL_RUN_TASK_POLICY = TaskPolicy(
    stream="anna_rag_eval_run_tasks",
    consumer_group="anna_rag_eval_run_workers",
    publish_interval_seconds=1.0,
    publish_batch_size=50,
    max_attempts=3,
    retry_backoff_seconds=10.0,
)

GRAPH_TASK_POLICY = TaskPolicy(
    stream="anna_rag_graph_tasks",
    consumer_group="anna_rag_graph_workers",
    publish_interval_seconds=1.0,
    publish_batch_size=20,
    max_attempts=5,
    retry_backoff_seconds=30.0,
)

REDIS_BACKEND = RedisBackend(maxlen=10_000, claim_min_idle_ms=60_000, claim_start_id="0-0")

UPLOAD_LIMITS = UploadLimits(
    max_bytes=10 * 1024 * 1024,
    allowed_suffixes=frozenset({".txt", ".md", ".csv", ".json", ".pdf"}),
)


def parse_allowed_extensions(raw: str) -> frozenset[str]:
    """把 ".txt,.md" 这种逗号串归一成 {".txt", ".md"}（补点、小写、去空）。"""

    out: set[str] = set()
    for item in raw.split(","):
        ext = item.strip().lower()
        if not ext:
            continue
        out.add(ext if ext.startswith(".") else f".{ext}")
    return frozenset(out)


__all__ = [
    "DOCUMENT_TASK_POLICY",
    "EVAL_RUN_TASK_POLICY",
    "EVAL_TASK_POLICY",
    "GRAPH_TASK_POLICY",
    "REDIS_BACKEND",
    "RedisBackend",
    "TaskPolicy",
    "UploadLimits",
    "parse_allowed_extensions",
]
