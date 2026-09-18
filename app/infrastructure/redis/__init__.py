"""Redis Stream 任务队列适配器：文档索引 / 出题 / 逐题评测共用基类，按类型分开注入。"""

from app.infrastructure.redis.base import RedisStreamQueue
from app.infrastructure.redis.document_task_queue import RedisDocumentTaskQueue
from app.infrastructure.redis.eval_run_task_queue import RedisEvalRunTaskQueue
from app.infrastructure.redis.eval_task_queue import RedisEvalTaskQueue
from app.infrastructure.redis.graph_task_queue import RedisGraphTaskQueue

__all__ = [
    "RedisDocumentTaskQueue",
    "RedisEvalRunTaskQueue",
    "RedisEvalTaskQueue",
    "RedisGraphTaskQueue",
    "RedisStreamQueue",
]
