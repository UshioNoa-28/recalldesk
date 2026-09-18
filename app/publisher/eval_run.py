"""EvalRunTaskPublisher 进程入口。

运行：
    python -m app.publisher.eval_run
"""

from __future__ import annotations

from app.application.services.publish.eval_run_task_publisher import EvalRunTaskPublisher
from app.worker import run_worker

if __name__ == "__main__":
    run_worker(EvalRunTaskPublisher, logger_name="recalldesk-eval-run-publisher")
