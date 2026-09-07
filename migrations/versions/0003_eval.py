"""eval tables (testsets / items)

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "eval_testsets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="generating"),
        sa.Column("progress_done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "eval_testset_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("testset_id", sa.String(length=36), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("answer_point_id", sa.String(length=1024), nullable=False),
        sa.Column("answer_document_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["testset_id"], ["eval_testsets.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_eval_testset_items_testset_id", "eval_testset_items", ["testset_id"]
    )
    op.create_unique_constraint(
        "uq_eval_testset_items_testset_point",
        "eval_testset_items",
        ["testset_id", "answer_point_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_eval_testset_items_testset_point", "eval_testset_items", type_="unique"
    )
    op.drop_index(
        "ix_eval_testset_items_testset_id", table_name="eval_testset_items"
    )
    op.drop_table("eval_testset_items")
    op.drop_table("eval_testsets")
