"""测试集用例编排：建集、加题（挂出题任务）、列表、详情、删除。

建集与加题是两个动作：先有一个空集，再一批批往里加题。加题与
DocumentService.ingest 同构——HTTP 请求内只做一个 PG 事务，真正出题由后台
EvalTaskPublisher → Redis Stream → EvalQuestionConsumer 完成，所以返回时
条目还是 pending。
"""

from __future__ import annotations

import uuid
from collections import defaultdict

from app.domain.eval import ChunkRef, EvalItemStatus, EvalTestSet, EvalTestSetItem
from app.ports.chunk_index import ChunkIndex
from app.ports.persistence.document_repository import DocumentRepository
from app.ports.persistence.eval_repository import EvalRepository
from app.ports.persistence.eval_task_repository import EvalTaskRepository
from app.ports.persistence.unit_of_work import UnitOfWork

DEFAULT_TESTSET_NAME = "未命名测试集"
# 一题最多带多少证据块：出题提示词的 token 预算随证据数线性涨，
# 多跳题现实里 2-3 块，5 是防手滑的天花板
MAX_EVIDENCE_CHUNKS_PER_ITEM = 5


class EvalService:
    """评测集用例编排。

    题目只存 chunk 坐标集合（平权，无主），不复制原文：分块文本住在检索
    索引（现 Neo4j）里，出题时按坐标回查。于是任何被引用的文档被删时它名下的
    题必须跟着没（0013 起无外键兜底：DocumentService.delete 调
    delete_items_referencing_document 显式清理，RESTRICT 外键当保险丝），
    因为那些坐标再也指向不到任何可命中的内容。
    """

    def __init__(
        self,
        *,
        eval_repository: EvalRepository,
        eval_task_repository: EvalTaskRepository,
        documents: DocumentRepository,
        chunk_index: ChunkIndex,
        unit_of_work: UnitOfWork,
    ) -> None:
        self._evals = eval_repository
        self._tasks = eval_task_repository
        self._documents = documents
        self._index = chunk_index
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

    async def add_items(
        self, testset_id: str, groups: list[list[ChunkRef]]
    ) -> dict:
        """往测试集追加题目 + 挂出题任务（同一事务）。

        一组坐标出一道题，证据平权无主（ordinal 仅拼装序）；**不查重**——
        2026-09-15 裁决：完全相同的组也照出，防手滑双击归前端的事。
        测试集不存在抛 KeyError；任何坐标指向不存在的文档/分块抛 ValueError。
        """

        if await self._evals.get_testset(testset_id) is None:
            raise KeyError(testset_id)

        normalized = [self._normalize_group(group) for group in groups]

        # 一组都没有：什么都不写，更不能把集 reopen 成 generating ——
        # 没有任务就没人会再调 finalize，它会永远卡在那儿。
        if not normalized:
            return await self.get_testset(testset_id)

        all_refs = [ref for group in normalized for ref in group]
        await self._require_indexed(all_refs)

        new_ids = await self._evals.add_testset_items(testset_id, normalized)
        await self._evals.reopen_testset(testset_id)
        for item_id in new_ids:
            await self._tasks.add(testset_id=testset_id, item_id=item_id)

        await self._unit_of_work.commit()
        return await self.get_testset(testset_id)

    @staticmethod
    def _normalize_group(group: list[ChunkRef]) -> list[ChunkRef]:
        """组内校验 + 去重（同一块在一道题里出现两次没有意义，跨题重复随你）。"""

        if not group:
            raise ValueError("每组题目至少要有一个 chunk")
        deduped = list(dict.fromkeys(group))
        if len(deduped) > MAX_EVIDENCE_CHUNKS_PER_ITEM:
            raise ValueError(
                f"一道题最多 {MAX_EVIDENCE_CHUNKS_PER_ITEM} 个证据 chunk"
                f"（这组有 {len(deduped)} 个）"
            )
        return deduped

    async def retry_failed_items(self, testset_id: str) -> dict:
        """重试本集全部失败题目：条目复位 pending、出题任务复位重投、集 reopen。

        只碰 FAILED 的题：ready 的题面和它的 run 历史原样不动，pending 的还在
        路上。不删条目重加，是因为 eval_run_items 对题目是 CASCADE——删了题，
        历史 run 里指向它的那些行会跟着一起没。任务行受 (item_id) 唯一约束，
        所以是复位旧行而不是补发新行。
        """

        if await self._evals.get_testset(testset_id) is None:
            raise KeyError(testset_id)
        failed = [
            item
            for item in await self._evals.list_testset_items(testset_id)
            if item.status is EvalItemStatus.FAILED
        ]
        # 没有可重做的就原样返回：reopen 了却没有任务，就没人再 finalize，
        # 集永远卡在 generating（与 add_items 同一个论点）
        if not failed:
            return await self.get_testset(testset_id)

        for item in failed:
            await self._evals.set_item_pending_retry(item.id)
            await self._tasks.reset_for_retry(item_id=item.id)
        await self._evals.reopen_testset(testset_id)
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
        原文由出题 worker 按坐标回查检索索引。按文档分组，一个文档只查一次。
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
                for row in await self._index.get_document_chunks(
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
        "status": testset.status,
        "progress_done": testset.progress_done,
        "progress_total": testset.progress_total,
        "error_message": testset.error_message,
        "created_at": testset.created_at.isoformat(),
    }


def _item_dict(item: EvalTestSetItem) -> dict:
    """answer_* 已随主坐标概念退役：坐标一律看 evidence 数组。"""

    return {
        "id": item.id,
        "query": item.query,
        "status": item.status,
        "error_message": item.error_message,
        "evidence": [
            {"document_id": ref.document_id, "chunk_index": ref.chunk_index}
            for ref in item.evidence_refs()
        ],
    }


__all__ = ["DEFAULT_TESTSET_NAME", "EvalService"]
