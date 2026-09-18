"""graph_tasks 发件箱 + eval_run_items 证据覆盖列（KG 链路的 PG 侧地基）

- graph_tasks：第四条 outbox 链路（文档索引成功后入队抽取任务），
  形状照抄 document_tasks（含 (status, next_retry_at) 领取索引）。
- eval_run_items +evidence_total/+evidence_matched：把"捞回了几块证据/该有几块"
  落行，evidence_coverage 指标由此聚合；历史行回填为 1/0（单证据旧题的
  coverage 会显示 0，属已知的一次性失真，重跑 run 即刷新）。

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "graph_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("operation", sa.String(length=16), nullable=False, server_default="extract"),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_graph_tasks_document_id", "graph_tasks", ["document_id"])
    op.create_index("ix_graph_tasks_status", "graph_tasks", ["status"])
    op.create_index(
        "ix_graph_tasks_status_next_retry", "graph_tasks", ["status", "next_retry_at"]
    )

    op.add_column(
        "eval_run_items",
        sa.Column("evidence_total", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "eval_run_items",
        sa.Column("evidence_matched", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("eval_run_items", "evidence_matched")
    op.drop_column("eval_run_items", "evidence_total")
    op.drop_index("ix_graph_tasks_status_next_retry", table_name="graph_tasks")
    op.drop_index("ix_graph_tasks_status", table_name="graph_tasks")
    op.drop_index("ix_graph_tasks_document_id", table_name="graph_tasks")
    op.drop_table("graph_tasks")
