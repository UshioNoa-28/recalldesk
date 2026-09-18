"""GraphTaskConsumer 进程入口。

运行：
    python -m app.consumer.graph
"""

from __future__ import annotations

from app.application.services.consume.graph_task_consumer import GraphTaskConsumer
from app.worker import run_worker

if __name__ == "__main__":
    run_worker(GraphTaskConsumer, logger_name="recalldesk-graph-consumer")
