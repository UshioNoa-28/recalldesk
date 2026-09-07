"""EvalQuestionConsumer 进程入口。

运行：
    python -m app.consumer.eval
"""

from __future__ import annotations

from app.application.services.consume.eval_question_consumer import EvalQuestionConsumer
from app.worker_entry import run_worker

if __name__ == "__main__":
    run_worker(EvalQuestionConsumer, logger_name="recalldesk-eval-consumer")
