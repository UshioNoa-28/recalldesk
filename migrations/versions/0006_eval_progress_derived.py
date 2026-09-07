"""eval testset: derive progress from items, drop dead columns

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-02

去掉 eval_testsets 的进度计数器（改由 items 聚合派生），并修掉
eval_testset_items 上几处模型问题：context_sha256 从未被读取、
answer_point_id 宽度抄了 storage_key、快照必需字段却可空。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("eval_testsets", "progress_done")
    op.drop_column("eval_testsets", "progress_total")
    op.drop_column("eval_testset_items", "context_sha256")

    op.alter_column(
        "eval_testset_items",
        "answer_point_id",
        existing_type=sa.String(length=1024),
        type_=sa.String(length=36),
        existing_nullable=False,
    )
    op.alter_column(
        "eval_testset_items",
        "document_name",
        existing_type=sa.String(length=255),
        nullable=False,
        existing_server_default=sa.text("''"),
    )
    # 没有 context_text 的条目永远出不了题，是废行：先前跑集成测试时
    # 有用例只填 point_id，这里清掉再收 NOT NULL（正常数据为空操作）。
    op.execute("DELETE FROM eval_testset_items WHERE context_text IS NULL")
    op.alter_column(
        "eval_testset_items",
        "context_text",
        existing_type=sa.Text(),
        nullable=False,
    )

    op.create_index(
        "ix_eval_items_testset_status",
        "eval_testset_items",
        ["testset_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_eval_items_testset_status", table_name="eval_testset_items")
    op.alter_column("eval_testset_items", "context_text", existing_type=sa.Text(), nullable=True)
    op.alter_column(
        "eval_testset_items",
        "document_name",
        existing_type=sa.String(length=255),
        nullable=True,
        existing_server_default=sa.text("''"),
    )
    op.alter_column(
        "eval_testset_items",
        "answer_point_id",
        existing_type=sa.String(length=36),
        type_=sa.String(length=1024),
        existing_nullable=False,
    )
    op.add_column(
        "eval_testset_items",
        sa.Column("context_sha256", sa.String(length=64), nullable=True),
    )
    # 计数器退回列，但历史进度无法从被删的列里还原：按当前条目状态回填
    op.add_column(
        "eval_testsets",
        sa.Column("progress_total", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "eval_testsets",
        sa.Column("progress_done", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute(
        """
        UPDATE eval_testsets AS ts
           SET progress_total = COALESCE(agg.total, 0),
               progress_done = COALESCE(agg.done, 0)
          FROM (
                SELECT testset_id,
                       COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE status <> 'pending') AS done
                  FROM eval_testset_items
                 GROUP BY testset_id
               ) AS agg
         WHERE ts.id = agg.testset_id
        """
    )
