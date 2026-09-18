"""GraphTaskPublisher 进程入口。

运行：
    python -m app.publisher.graph
"""

from __future__ import annotations

from app.application.services.publish.graph_task_publisher import GraphTaskPublisher
from app.worker import run_worker

if __name__ == "__main__":
    run_worker(GraphTaskPublisher, logger_name="recalldesk-graph-publisher")
