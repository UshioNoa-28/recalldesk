"""eval run task outbox (eval_run_tasks): 逐题评测任务，run 开跑时按 ready 题 fan-out

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "eval_run_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("item_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["eval_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["item_id"], ["eval_testset_items.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        # 一题在一次 run 里只有一条任务（publisher 重投=复位这一行）
        sa.UniqueConstraint(
            "run_id", "item_id", name="uq_eval_run_tasks_run_item"
        ),
    )
    # 历史遗留的 running 行：run 一旦改走队列，启动扫（fail_stale_runs）就删了，
    # 但库里可能还躺着上次进程死掉留下的 running —— 没有任务行的它们永远不会有人
    # 收尾，直接标 failed 交给这套新语义接管。
    op.execute(
        """
        UPDATE eval_runs
        SET status = 'failed',
            error_message = '升级为队列化评测：旧进程内 run 不再续跑',
            finished_at = now()
        WHERE status = 'running'
        """
    )
    op.create_index(
        "ix_eval_run_tasks_run_id", "eval_run_tasks", ["run_id"]
    )
    # publisher 扫 PENDING（带 next_retry_at 退避过滤）
    op.create_index(
        "ix_eval_run_tasks_status_next_retry",
        "eval_run_tasks",
        ["status", "next_retry_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_eval_run_tasks_status_next_retry", table_name="eval_run_tasks"
    )
    op.drop_index("ix_eval_run_tasks_run_id", table_name="eval_run_tasks")
    op.drop_constraint(
        "uq_eval_run_tasks_run_item", "eval_run_tasks", type_="unique"
    )
    op.drop_table("eval_run_tasks")
