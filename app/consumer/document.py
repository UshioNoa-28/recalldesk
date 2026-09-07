"""DocumentTaskConsumer 进程入口。

运行：
    python -m app.consumer.document
"""

from __future__ import annotations

from app.application.services.consume.document_task_consumer import DocumentTaskConsumer
from app.worker_entry import run_worker

if __name__ == "__main__":
    run_worker(DocumentTaskConsumer, logger_name="recalldesk-consumer")
