"""task_outbox -> document_tasks：与 eval_tasks 对称命名，索引一并跟上。

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-07
"""

from __future__ import annotations

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("task_outbox", "document_tasks")
    # ALTER TABLE RENAME 只动表名，索引留在原地，得逐个改名
    op.execute("ALTER INDEX ix_task_outbox_document_id RENAME TO ix_document_tasks_document_id")
    op.execute("ALTER INDEX ix_task_outbox_status RENAME TO ix_document_tasks_status")


def downgrade() -> None:
    op.execute("ALTER INDEX ix_document_tasks_document_id RENAME TO ix_task_outbox_document_id")
    op.execute("ALTER INDEX ix_document_tasks_status RENAME TO ix_task_outbox_status")
    op.rename_table("document_tasks", "task_outbox")
