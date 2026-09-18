"""SQLAlchemy ORM 模型，按聚合拆分；外部统一从 app.infrastructure.postgres.tables 导入。

拆分纪律：一个文件 = 一个聚合根及其从属表，relationship 尽量落在同文件内
（testsets：测试集+题目+证据+出题任务；runs：run+逐题结果+逐题任务；
documents：文档+出箱任务）。跨聚合只靠外键字符串引用，不跨文件引 ORM 类。
"""

from app.infrastructure.postgres.tables.base import Base, utc_now
from app.infrastructure.postgres.tables.documents import (
    DocumentTable,
    DocumentTaskTable,
    document_from_row,
)
from app.infrastructure.postgres.tables.graph import GraphTaskTable
from app.infrastructure.postgres.tables.runs import (
    EvalRunItemTable,
    EvalRunTable,
    EvalRunTaskTable,
)
from app.infrastructure.postgres.tables.testsets import (
    EvalTaskTable,
    EvalTestSetItemEvidenceTable,
    EvalTestSetItemTable,
    EvalTestSetTable,
)

__all__ = [
    "Base",
    "DocumentTable",
    "DocumentTaskTable",
    "EvalRunItemTable",
    "EvalRunTable",
    "EvalRunTaskTable",
    "EvalTaskTable",
    "EvalTestSetItemEvidenceTable",
    "EvalTestSetItemTable",
    "EvalTestSetTable",
    "GraphTaskTable",
    "document_from_row",
    "utc_now",
]
