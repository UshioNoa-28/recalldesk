"""Redis Stream 任务队列适配器：文档索引与 Eval 出题共用基类，按类型分开注入。"""

from app.infrastructure.queues.base import RedisStreamQueue
from app.infrastructure.queues.document_task_queue import RedisDocumentTaskQueue
from app.infrastructure.queues.eval_task_queue import RedisEvalTaskQueue

__all__ = ["RedisDocumentTaskQueue", "RedisEvalTaskQueue", "RedisStreamQueue"]
