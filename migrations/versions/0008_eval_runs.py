"""eval run tables (runs / run_items)

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # eval_runs 从来没有真表：早期 ORM 里定义过一版又被删掉，迁移链里一直没建。
    # 这次 run 真要跑了，才补上第一版。
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("testset_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="running"),
        sa.Column(
            "config_json", JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"
        ),
        sa.Column("metrics_json", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["testset_id"], ["eval_testsets.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # 历史列表按 testset 挑，跑完的集也常常要一次看全部
    op.create_index("ix_eval_runs_testset_id", "eval_runs", ["testset_id"])

    # 逐题结果只存不可再生的事实：mrr 是 hit_rank 的倒数、low_recall 是
    # recall 是否为 0，都能从行内其他列算出来，落列就得在改口径时同步维护。
    # 也没有进度列：跑完几题看这里有几行就知道。
    op.create_table(
        "eval_run_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("testset_item_id", sa.String(length=36), nullable=False),
        sa.Column("hit_rank", sa.Integer(), nullable=True),
        sa.Column("recall", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Double(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["run_id"], ["eval_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["testset_item_id"], ["eval_testset_items.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        # 一题在一次 run 里只有一条结果：执行器靠它做「重跑不重复写」的守卫
        sa.UniqueConstraint(
            "run_id", "testset_item_id", name="uq_eval_run_items_run_item"
        ),
    )
    # 不单独建 run_id 索引：上面那条唯一约束以 run_id 打头，前缀查询走它。
    # 从题目侧级联删、以及「这题在本次 run 里结没结果」的子查询都走下面这条。
    op.create_index(
        "ix_eval_run_items_testset_item_id", "eval_run_items", ["testset_item_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_eval_run_items_testset_item_id", table_name="eval_run_items"
    )
    op.drop_constraint(
        "uq_eval_run_items_run_item", "eval_run_items", type_="unique"
    )
    op.drop_table("eval_run_items")
    op.drop_index("ix_eval_runs_testset_id", table_name="eval_runs")
    op.drop_table("eval_runs")
