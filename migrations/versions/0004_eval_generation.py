"""eval generation: item snapshot/status fields + eval_tasks outbox

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 出题流程改造：item 创建时不再有 query（LLM 异步生成），
    # 同时快照 chunk 原文，消费端不依赖 Qdrant。
    op.alter_column("eval_testset_items", "query", existing_type=sa.Text(), nullable=True)
    op.add_column(
        "eval_testset_items",
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
    )
    op.add_column("eval_testset_items", sa.Column("error_message", sa.Text(), nullable=True))
    op.add_column(
        "eval_testset_items",
        sa.Column("answer_chunk_index", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "eval_testset_items",
        sa.Column("document_name", sa.String(length=255), nullable=False, server_default=""),
    )
    op.add_column("eval_testset_items", sa.Column("context_text", sa.Text(), nullable=True))
    op.add_column(
        "eval_testset_items",
        sa.Column("context_sha256", sa.String(length=64), nullable=True),
    )

    op.create_table(
        "eval_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("testset_id", sa.String(length=36), nullable=False),
        sa.Column("item_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["testset_id"], ["eval_testsets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["item_id"], ["eval_testset_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_id", name="uq_eval_tasks_item_id"),
    )
    op.create_index("ix_eval_tasks_testset_id", "eval_tasks", ["testset_id"])
    op.create_index("ix_eval_tasks_status", "eval_tasks", ["status"])


def downgrade() -> None:
    op.drop_index("ix_eval_tasks_status", table_name="eval_tasks")
    op.drop_index("ix_eval_tasks_testset_id", table_name="eval_tasks")
    op.drop_table("eval_tasks")
    op.drop_column("eval_testset_items", "context_sha256")
    op.drop_column("eval_testset_items", "context_text")
    op.drop_column("eval_testset_items", "document_name")
    op.drop_column("eval_testset_items", "answer_chunk_index")
    op.drop_column("eval_testset_items", "error_message")
    op.drop_column("eval_testset_items", "status")
    op.alter_column("eval_testset_items", "query", existing_type=sa.Text(), nullable=False)
