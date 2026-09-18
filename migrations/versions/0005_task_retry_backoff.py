"""task retry backoff: next_retry_at on task_outbox / eval_tasks

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 失败重试改为 DB 驱动：record_failure 把任务翻回 PENDING 并按指数退避
    # 写入下次重试时间，publisher 的 list_pending 只领取到期的任务。
    op.add_column(
        "task_outbox",
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "eval_tasks",
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("eval_tasks", "next_retry_at")
    op.drop_column("task_outbox", "next_retry_at")
