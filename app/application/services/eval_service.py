"""测试集用例编排：建集、加题（挂出题任务）、列表、详情、删除。

建集与加题是两个动作：先有一个空集，再一批批往里加题。加题与
DocumentService.ingest 同构——HTTP 请求内只做一个 PG 事务，真正出题由后台
EvalTaskPublisher → Redis Stream → EvalQuestionConsumer 完成，所以返回时
条目还是 pending。
"""

from __future__ import annotations

import uuid
from collections import defaultdict

from app.domain.eval import ChunkRef, EvalTestSet, EvalTestSetItem
from app.ports.document_repository import DocumentRepository
from app.ports.eval_repository import EvalRepository
from app.ports.eval_task_repository import EvalTaskRepository
from app.ports.unit_of_work import UnitOfWork
from app.ports.vector_repository import VectorRepository

DEFAULT_TESTSET_NAME = "未命名测试集"


class EvalService:
    """评测集用例编排。

    题目只存 chunk 坐标 (document_id, chunk_index)，不复制原文：分块文本的
    唯一权威在 Qdrant，出题时按坐标回查。于是文档被删时它名下的题必须跟着
    没（外键级联），因为那个坐标再也指向不到任何可命中的内容。
    """

    def __init__(
        self,
        *,
        eval_repository: EvalRepository,
        eval_task_repository: EvalTaskRepository,
        documents: DocumentRepository,
        vector_repository: VectorRepository,
        unit_of_work: UnitOfWork,
    ) -> None:
        self._evals = eval_repository
        self._tasks = eval_task_repository
        self._documents = documents
        self._vectors = vector_repository
        self._unit_of_work = unit_of_work

    async def create_testset(self, *, name: str | None) -> dict:
        """只建一个空测试集：题目靠 add_items 往里加。"""

        testset_id = str(uuid.uuid4())
        await self._evals.create_testset(
            testset_id=testset_id,
            name=(name or "").strip() or DEFAULT_TESTSET_NAME,
        )
        await self._unit_of_work.commit()
        return await self.get_testset(testset_id)

    async def add_items(self, testset_id: str, chunk_refs: list[ChunkRef]) -> dict:
        """往测试集追加题目 + 挂出题任务（同一事务）。

        集内坐标唯一（有唯一约束），所以已经在集里的坐标直接跳过：
        同一批勾选重复提交是安全的。测试集不存在抛 KeyError；
        坐标指向不存在的文档或分块抛 ValueError。
        """

        if await self._evals.get_testset(testset_id) is None:
            raise KeyError(testset_id)

        existing = {
            (item.answer_document_id, item.answer_chunk_index)
            for item in await self._evals.list_testset_items(testset_id)
        }
        wanted = list(
            dict.fromkeys((ref.document_id, ref.chunk_index) for ref in chunk_refs)
        )
        new_coords = [coord for coord in wanted if coord not in existing]
        # 一道新题都没有：什么都不写，更不能把集 reopen 成 generating ——
        # 没有任务就没人会再调 finalize，它会永远卡在那儿。
        if not new_coords:
            return await self.get_testset(testset_id)

        new_refs = [
            ChunkRef(document_id=document_id, chunk_index=index)
            for document_id, index in new_coords
        ]
        await self._require_indexed(new_refs)

        await self._evals.add_testset_items(testset_id, new_refs)
        await self._evals.reopen_testset(testset_id)
        # item id 由仓储生成，同 session 的这条 select 会先 autoflush 出来；
        # 坐标在集内唯一，所以可以拿它当身份挑出新增的那几道
        pending = set(new_coords)
        for item in await self._evals.list_testset_items(testset_id):
            if (item.answer_document_id, item.answer_chunk_index) in pending:
                await self._tasks.add(testset_id=testset_id, item_id=item.id)

        await self._unit_of_work.commit()
        return await self.get_testset(testset_id)

    async def list_testsets(self) -> dict:
        """评测集列表（含派生进度），按创建时间降序。"""

        return {
            "testsets": [_testset_dict(ts) for ts in await self._evals.list_testsets()]
        }

    async def get_testset(self, testset_id: str) -> dict:
        """单个评测集 + 它的全题目；不存在抛 KeyError。"""

        testset = await self._evals.get_testset(testset_id)
        if testset is None:
            raise KeyError(testset_id)
        items = await self._evals.list_testset_items(testset_id)
        return {**_testset_dict(testset), "items": [_item_dict(item) for item in items]}

    async def delete_testset(self, testset_id: str) -> None:
        """删除评测集：题目与未发出的出题任务随外键级联一起走。"""

        if await self._evals.get_testset(testset_id) is None:
            raise KeyError(testset_id)
        await self._evals.delete_testset(testset_id)
        await self._unit_of_work.commit()

    async def _require_indexed(self, refs: list[ChunkRef]) -> None:
        """坐标必须指向真实已索引的分块，否则抛 ValueError（→ 400）。

        这里刻意不用 KeyError：路径上的资源是测试集，文档和切片都只是请求体里的
        值，指向不存在的东西是坏输入而不是找不到资源。只验存在性、不取原文：
        原文由出题 worker 按坐标回查 Qdrant。按文档分组，一个文档只 scroll 一次。
        """

        grouped: dict[str, list[int]] = defaultdict(list)
        for ref in refs:
            grouped[ref.document_id].append(ref.chunk_index)

        for document_id, indexes in grouped.items():
            document = await self._documents.get(document_id)
            if document is None:
                raise ValueError(f"文档 {document_id} 不存在（可能已被删除）")
            indexed = {
                int(row["chunk_index"])
                for row in await self._vectors.get_document_chunks(
                    document_id=document_id
                )
            }
            for chunk_index in indexes:
                if chunk_index not in indexed:
                    raise ValueError(
                        f"文档「{document.name}」没有切片 #{chunk_index}（共 {len(indexed)} 块）"
                    )


def _testset_dict(testset: EvalTestSet) -> dict:
    return {
        "id": testset.id,
        "name": testset.name,
        "status": testset.status.value,
        "progress_done": testset.progress_done,
        "progress_total": testset.progress_total,
        "error_message": testset.error_message,
        "created_at": testset.created_at.isoformat(),
    }


def _item_dict(item: EvalTestSetItem) -> dict:
    return {
        "id": item.id,
        "query": item.query,
        "status": item.status.value,
        "error_message": item.error_message,
        "answer_document_id": item.answer_document_id,
        "answer_chunk_index": item.answer_chunk_index,
    }


__all__ = ["DEFAULT_TESTSET_NAME", "EvalService"]
