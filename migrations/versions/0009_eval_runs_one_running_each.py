"""eval_runs：同一测试集同时只允许一个 running（部分唯一索引）

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 迁移只在 API 启动时跑：此刻还存在的 running 行只可能是进程崩溃的遗留
    # （lifespan 里的 fail_stale_runs 做的就是这件事，但它排在迁移之后）。
    # 先收尾才能安全建唯一索引，否则历史脏数据会让建索引直接失败。
    op.execute(
        "UPDATE eval_runs SET status = 'failed',"
        " error_message = '进程重启，运行被中断（0009 迁移收尾）'"
        " WHERE status = 'running'"
    )
    # _require_idle 的「查 running 再插入」之间有并发窗口，这条部分唯一索引
    # 是数据库层面的最终防线：并发 start_run 只有一个能提交成功。
    op.create_index(
        "uq_eval_runs_running_per_testset",
        "eval_runs",
        ["testset_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )


def downgrade() -> None:
    op.drop_index("uq_eval_runs_running_per_testset", table_name="eval_runs")
