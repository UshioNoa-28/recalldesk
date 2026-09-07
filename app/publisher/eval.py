"""EvalTaskPublisher 进程入口。

运行：
    python -m app.publisher.eval
"""

from __future__ import annotations

from app.application.services.publish.eval_task_publisher import EvalTaskPublisher
from app.worker_entry import run_worker

if __name__ == "__main__":
    run_worker(EvalTaskPublisher, logger_name="recalldesk-eval-publisher")
