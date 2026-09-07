"""DocumentTaskPublisher 进程入口。

运行：
    python -m app.publisher.document
"""

from __future__ import annotations

from app.application.services.publish.document_task_publisher import DocumentTaskPublisher
from app.worker_entry import run_worker

if __name__ == "__main__":
    run_worker(DocumentTaskPublisher, logger_name="recalldesk-publisher")
