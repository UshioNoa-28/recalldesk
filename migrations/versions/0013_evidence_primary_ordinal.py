"""0013 证据表升为坐标权威：items 删主坐标列

多对多世界里"主"不再需要一个专属的列，它只是集合里 ordinal=0 的那个成员：

1. evidence +ordinal（0 = 主坐标/答案所在，其余为补充证据；同时是出题拼装顺序），
   unique(item_id, ordinal) 保证一题恰有一个主；
2. 回填历史空洞：0011 建表之后、写入路径补上证据投影之前创建的题没有证据行，
   从旧列造出 ordinal=0 的那一行（0011 当年回填过的行不受影响）；
3. items 删 answer_document_id / answer_chunk_index 两列与
   uq_eval_testset_items_testset_chunk 唯一约束——"一个主坐标只出一道题"
   由 DB 约束降级为服务层（EvalService.add_items 查重）保证；
4. evidence.document_id 外键 CASCADE -> RESTRICT：items 不再挂 documents 之后，
   CASCADE 变成静默制造"零证据僵尸题"的凶手；RESTRICT 是忘 purge 时
   把删文档事务撞回来的有声保险丝（清理路径：DocumentService.delete ->
   delete_items_referencing_document，先删题再删文档行）。

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "eval_testset_item_evidence",
        sa.Column("ordinal", sa.Integer(), nullable=False, server_default="0"),
    )
    # 回填空洞必须在删列之前：老题的证据行只有旧列里这对坐标可用
    op.execute(
        """
        INSERT INTO eval_testset_item_evidence (item_id, document_id, chunk_index, ordinal)
        SELECT i.id, i.answer_document_id, i.answer_chunk_index, 0
        FROM eval_testset_items i
        WHERE NOT EXISTS (
            SELECT 1 FROM eval_testset_item_evidence e WHERE e.item_id = i.id
        )
        """
    )
    op.create_unique_constraint(
        "uq_eval_evidence_item_ordinal",
        "eval_testset_item_evidence",
        ["item_id", "ordinal"],
    )

    op.drop_constraint(
        "uq_eval_testset_items_testset_chunk", "eval_testset_items", type_="unique"
    )
    # PG 删列自动带走列上的索引（ix_eval_testset_items_answer_document_id）
    op.drop_column("eval_testset_items", "answer_document_id")
    op.drop_column("eval_testset_items", "answer_chunk_index")

    op.drop_constraint(
        "eval_testset_item_evidence_document_id_fkey",
        "eval_testset_item_evidence",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_evidence_document",
        "eval_testset_item_evidence",
        "documents",
        ["document_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    # 反向：列从 ordinal=0 的证据行重建。没有主证据行的题（不该存在）会让
    # SET NOT NULL 直接失败——宁可 downgrade 报错，还半吊子恢复
    op.add_column("eval_testset_items", sa.Column("answer_document_id", sa.String(36)))
    op.add_column("eval_testset_items", sa.Column("answer_chunk_index", sa.Integer()))
    op.execute(
        """
        UPDATE eval_testset_items i
        SET answer_document_id = e.document_id,
            answer_chunk_index = e.chunk_index
        FROM eval_testset_item_evidence e
        WHERE e.item_id = i.id AND e.ordinal = 0
        """
    )
    # 没有主证据行的题（不该存在）此时仍是 NULL —— 下一条 SET NOT NULL 会直接失败：
    # 宁可 downgrade 报错，也不半吊子恢复
    op.alter_column(
        "eval_testset_items", "answer_document_id", existing_type=sa.String(36), nullable=False
    )
    op.alter_column(
        "eval_testset_items", "answer_chunk_index", existing_type=sa.Integer(), nullable=False
    )
    op.create_foreign_key(
        "eval_testset_items_answer_document_id_fkey",
        "eval_testset_items",
        "documents",
        ["answer_document_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_eval_testset_items_answer_document_id",
        "eval_testset_items",
        ["answer_document_id"],
    )
    op.create_unique_constraint(
        "uq_eval_testset_items_testset_chunk",
        "eval_testset_items",
        ["testset_id", "answer_document_id", "answer_chunk_index"],
    )

    op.drop_constraint(
        "fk_evidence_document", "eval_testset_item_evidence", type_="foreignkey"
    )
    op.create_foreign_key(
        "eval_testset_item_evidence_document_id_fkey",
        "eval_testset_item_evidence",
        "documents",
        ["document_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(
        "uq_eval_evidence_item_ordinal", "eval_testset_item_evidence", type_="unique"
    )
    # 多证据题会退化成"只剩主坐标"：与 0011 的 downgrade 同样的已知有损
    op.drop_column("eval_testset_item_evidence", "ordinal")
