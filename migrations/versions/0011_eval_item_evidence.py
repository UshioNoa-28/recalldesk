"""eval_testset_item_evidence：题目证据集（item -> chunk 多对多的关联表）。

多跳评测的地基第一步：一道题的 ground truth 从单坐标泛化为坐标集合。
本迁移是纯增量——旧列 answer_document_id / answer_chunk_index 原样保留并继续
作为读路径，数据在这里回填；代码切到证据表、删旧列（含重建"文档删除 -> 题目
级联消失"的外键语义，旧列的 FK CASCADE 是现在唯一的保险丝）都放在下一步的
0012，两步各自可独立回滚。

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "eval_testset_item_evidence",
        sa.Column("item_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["item_id"], ["eval_testset_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("item_id", "document_id", "chunk_index"),
    )
    # item_id 走主键前缀即可；document_id 得有自己的索引：
    # 文档删除时它的 CASCADE 从这里反查，反向查询（这个块被哪些题引用）也靠它。
    # 名字按 SQLAlchemy 默认约定来，免得 autogenerate 把 ORM 和 DB 判成不一致
    op.create_index(
        "ix_eval_testset_item_evidence_document_id",
        "eval_testset_item_evidence",
        ["document_id"],
    )
    # 回填：现有题全部是单证据题，N=1 是 N 的特例（SELECT 逐行唯一，不会撞主键）
    op.execute(
        "INSERT INTO eval_testset_item_evidence (item_id, document_id, chunk_index)"
        " SELECT id, answer_document_id, answer_chunk_index FROM eval_testset_items"
    )


def downgrade() -> None:
    # 此表是旧列的投影，丢弃不损数据；但若 0012 之后（旧列已删、多证据题存在）
    # 再执行 downgrade，那些题会失去 ground truth —— 0012 落地时要把回来这里
    op.drop_index(
        "ix_eval_testset_item_evidence_document_id", table_name="eval_testset_item_evidence"
    )
    op.drop_table("eval_testset_item_evidence")
