"""EvalRunConsumer 进程入口。

运行：
    python -m app.consumer.eval_run
"""

from __future__ import annotations

from app.application.services.consume.eval_run_consumer import EvalRunConsumer
from app.worker import run_worker

if __name__ == "__main__":
    run_worker(EvalRunConsumer, logger_name="recalldesk-eval-run-consumer")
