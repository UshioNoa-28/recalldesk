"""eval items: 去掉出题快照列，answer_document_id 改成真外键

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-03

题目不再复制分块原文，只存坐标 (answer_document_id, answer_chunk_index)：
文本的唯一权威在 Qdrant，出题时按坐标回查（点 id 是坐标的纯函数）。
少了原文这一层副本，answer_document_id 就必须是真外键 —— 文档被删则它的
点一起消失，题目再也指不到可命中的内容，于是级联删掉而不是留成废行。

唯一约束也从 (testset_id, answer_point_id) 换成坐标：point id 现在是算出来的，
按它约束等于按坐标约束，但留着那列就得连原文一起留。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 收外键前先清掉两类会被挡住的行：指向不存在文档的（本来也出不了题），
    # 以及同集内坐标重复的（旧约束按 point id 挡，历史上写进过假 id）。
    # eval_tasks 对 item 是 CASCADE，删掉的重复题其任务一起走。
    op.execute(
        """
        DELETE FROM eval_testset_items
         WHERE answer_document_id NOT IN (SELECT id FROM documents)
        """
    )
    op.execute(
        """
        DELETE FROM eval_testset_items AS a
         USING eval_testset_items AS b
         WHERE a.ctid < b.ctid
           AND a.testset_id = b.testset_id
           AND a.answer_document_id = b.answer_document_id
           AND a.answer_chunk_index = b.answer_chunk_index
        """
    )

    op.drop_constraint(
        "uq_eval_testset_items_testset_point", "eval_testset_items", type_="unique"
    )
    op.drop_column("eval_testset_items", "context_text")
    op.drop_column("eval_testset_items", "document_name")
    op.drop_column("eval_testset_items", "answer_point_id")

    op.create_unique_constraint(
        "uq_eval_testset_items_testset_chunk",
        "eval_testset_items",
        ["testset_id", "answer_document_id", "answer_chunk_index"],
    )
    op.create_foreign_key(
        "fk_eval_testset_items_answer_document",
        "eval_testset_items",
        "documents",
        ["answer_document_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # documents.id 上有 PK 索引，但从文档侧级联删要扫的是这一侧
    op.create_index(
        "ix_eval_testset_items_answer_document_id",
        "eval_testset_items",
        ["answer_document_id"],
    )


def downgrade() -> None:
    # 结构可以还原，快照内容不行：context_text / document_name 回填成空串，
    # answer_point_id 用 item id 顶替（只要求集内唯一，值本身无意义）。
    op.drop_index(
        "ix_eval_testset_items_answer_document_id",
        table_name="eval_testset_items",
    )
    op.drop_constraint(
        "fk_eval_testset_items_answer_document",
        "eval_testset_items",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_eval_testset_items_testset_chunk", "eval_testset_items", type_="unique"
    )

    op.add_column(
        "eval_testset_items",
        sa.Column("answer_point_id", sa.String(length=36), nullable=True),
    )
    op.execute("UPDATE eval_testset_items SET answer_point_id = id")
    op.alter_column(
        "eval_testset_items", "answer_point_id", existing_type=sa.String(36), nullable=False
    )
    op.add_column(
        "eval_testset_items",
        sa.Column("document_name", sa.String(length=255), nullable=False, server_default=""),
    )
    op.add_column(
        "eval_testset_items",
        sa.Column("context_text", sa.Text(), nullable=False, server_default=""),
    )
    op.create_unique_constraint(
        "uq_eval_testset_items_testset_point",
        "eval_testset_items",
        ["testset_id", "answer_point_id"],
    )
