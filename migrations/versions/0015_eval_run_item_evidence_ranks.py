"""eval_run_items +evidence_ranks_json：MAP@k 的名次快照（多跳评分换血）

对齐 2WikiMultihopQA / MultiHop-RAG 口径：joint@k 从既有 matched/total 两列
派生零成本，但 map@k 需要"每块证据排在第几"，只存了 hit_rank（首块名次）
的老行补不出来——加一列 JSONB 存升序名次表。历史行留 NULL，聚合侧按 0 计
（口径：老 run 的数字不上新榜，重跑即刷新）。

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "eval_run_items",
        sa.Column("evidence_ranks_json", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("eval_run_items", "evidence_ranks_json")
