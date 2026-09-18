"""eval_run_items -recall：文档级宽口径退役（多跳评分精简为三指标）

2026-09-15 裁决：聚合只留 recall@k（块级全在，原 joint_hit 派生）、
map@k、evidence_coverage。文档级 recall 列（"证据文档进没进 top-k"）
与块级口径重复且更宽（找对篇挑错块也给分），连同 low_recall 前端旗
一起退役。历史 run 重跑即按新口径重算；hit_rank / evidence_* 列不动。

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("eval_run_items", "recall")


def downgrade() -> None:
    op.add_column(
        "eval_run_items",
        sa.Column("recall", sa.Integer(), nullable=False, server_default="0"),
    )
