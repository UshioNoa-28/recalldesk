"""EvalTaskRepository 集成测试（需要本地 Postgres，连不上则跳过）。

只覆盖任务生命周期（SKIP LOCKED 领取 / 标记 / 重试退避）；
题目与测试集状态的回写在 test_eval_repository.py。
"""

from __future__ import annotations

import unittest

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.domain.eval import ChunkRef, EvalTaskStatus
from app.infrastructure.eval_repository import SqlAlchemyEvalRepository
from app.infrastructure.eval_task_repository import SqlAlchemyEvalTaskRepository

pytestmark = pytest.mark.integration

URL = "postgresql+asyncpg://rag:rag@127.0.0.1:5435/anna_rag"
DOC_ID = "it-eval-task-doc"


def _postgres_alive() -> bool:
    try:
        import asyncio

        async def _ping() -> bool:
            # timeout：端口被防火墙过滤时（丢包不拒绝）避免 asyncpg 默认 60s 等待
            engine = create_async_engine(URL, pool_pre_ping=True, connect_args={"timeout": 3})
            try:
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
            finally:
                await engine.dispose()
            return True

        return asyncio.run(_ping())
    except Exception:
        return False


@unittest.skipUnless(_postgres_alive(), f"本地 Postgres 不可用: {URL}")
class EvalTaskRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def _delete_it_rows(self) -> None:
        async with self._session_factory() as session:
            await session.execute(text("DELETE FROM eval_testsets WHERE name LIKE 'IT出题集%'"))
            await session.execute(text("DELETE FROM documents WHERE id = :doc"), {"doc": DOC_ID})
            await session.commit()

    async def asyncSetUp(self) -> None:
        self._engine = create_async_engine(URL)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)
        await self._delete_it_rows()
        # 题目只存坐标，answer_document_id 是真外键：没有这行文档就写不进题目
        async with self._session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO documents (id, name, storage_key, size_bytes,"
                    " checksum_sha256, status) VALUES (:id, 'IT文档', :key, 1, 'sha',"
                    " 'success')"
                ),
                {"id": DOC_ID, "key": f"{DOC_ID}.txt"},
            )
            await session.commit()

    async def _create_testset_with_tasks(
        self, testset_id: str, chunk_indexes: list[int]
    ) -> None:
        """建测试集 + 题目 + 一条任务/题目：单个事务（真实创建用例的形状）。"""

        async with self._session_factory() as session:
            evals = SqlAlchemyEvalRepository(session)
            tasks = SqlAlchemyEvalTaskRepository(session)
            await evals.create_testset(testset_id=testset_id, name=f"IT出题集-{testset_id}")
            await evals.add_testset_items(
                testset_id,
                [
                    ChunkRef(document_id=DOC_ID, chunk_index=index)
                    for index in chunk_indexes
                ],
            )
            for item in await evals.list_testset_items(testset_id):
                await tasks.add(testset_id=testset_id, item_id=item.id)
            await session.commit()

    async def asyncTearDown(self) -> None:
        await self._delete_it_rows()
        await self._engine.dispose()

    async def test_claim_then_mark_queued_then_success(self) -> None:
        await self._create_testset_with_tasks("ts-task-1", [0])

        async with self._session_factory() as session:
            tasks = SqlAlchemyEvalTaskRepository(session)
            pending = await tasks.list_pending(limit=10)
            self.assertEqual(1, len(pending))
            self.assertEqual(EvalTaskStatus.PENDING, pending[0].status)
            self.assertEqual("ts-task-1", pending[0].testset_id)
            await tasks.mark_queued(pending[0].id)
            await session.commit()
            task_id = pending[0].id

        async with self._session_factory() as session:
            tasks = SqlAlchemyEvalTaskRepository(session)
            # QUEUE 状态不再被领取
            self.assertEqual([], await tasks.list_pending(limit=10))
            await tasks.mark_success(task_id)
            await session.commit()

        async with self._session_factory() as session:
            task = await SqlAlchemyEvalTaskRepository(session).get(task_id)
            self.assertEqual(EvalTaskStatus.SUCCESS, task.status)
            self.assertIsNotNone(task.queued_at)

    async def test_record_failure_backs_off_until_next_retry(self) -> None:
        await self._create_testset_with_tasks("ts-task-2", [0])

        async with self._session_factory() as session:
            tasks = SqlAlchemyEvalTaskRepository(session)
            (entry,) = await tasks.list_pending(limit=10)
            await tasks.record_failure(entry.id, error="llm down")
            await session.commit()

        async with self._session_factory() as session:
            tasks = SqlAlchemyEvalTaskRepository(session)
            # 退避期内不可领取，且回到 PENDING 等 publisher 重投
            self.assertEqual([], await tasks.list_pending(limit=10))
            task = await tasks.get(entry.id)
            self.assertEqual(EvalTaskStatus.PENDING, task.status)
            self.assertEqual(1, task.attempts)
            self.assertEqual("llm down", task.last_error)

        async with self._session_factory() as session:
            # 把退避时间拨到过去：模拟等待后重新可领取
            await session.execute(
                text("UPDATE eval_tasks SET next_retry_at = now() - interval '1 second'")
            )
            await session.commit()

        async with self._session_factory() as session:
            tasks = SqlAlchemyEvalTaskRepository(session)
            pending = await tasks.list_pending(limit=10)
            self.assertEqual([entry.id], [item.id for item in pending])

    async def test_mark_failed_is_terminal(self) -> None:
        await self._create_testset_with_tasks("ts-task-3", [0])

        async with self._session_factory() as session:
            tasks = SqlAlchemyEvalTaskRepository(session)
            (entry,) = await tasks.list_pending(limit=10)
            for _ in range(5):  # eval_task_max_attempts = 5
                await tasks.record_failure(entry.id, error="llm down")
            await tasks.mark_failed(entry.id)
            await session.commit()

        async with self._session_factory() as session:
            tasks = SqlAlchemyEvalTaskRepository(session)
            self.assertEqual([], await tasks.list_pending(limit=10))
            self.assertEqual(EvalTaskStatus.FAILED, (await tasks.get(entry.id)).status)

    async def test_get_missing_returns_none_and_mark_raises(self) -> None:
        async with self._session_factory() as session:
            tasks = SqlAlchemyEvalTaskRepository(session)
            self.assertIsNone(await tasks.get("nope"))
            with self.assertRaises(KeyError):
                await tasks.mark_success("nope")

    async def test_one_task_per_item(self) -> None:
        """uq_eval_tasks_item_id：同一条目重复挂任务会被拒。"""

        await self._create_testset_with_tasks("ts-task-4", [0])
        async with self._session_factory() as session:
            tasks = SqlAlchemyEvalTaskRepository(session)
            (entry,) = await tasks.list_pending(limit=10)
            with self.assertRaises(IntegrityError):
                await tasks.add(testset_id="ts-task-4", item_id=entry.item_id)
                await session.flush()

    async def test_deleting_the_document_takes_items_and_their_tasks(self) -> None:
        """0007 的整条级联：文档 -> 题目 -> 未发出的出题任务。

        DocumentService.delete 只删 documents 行，剩下的靠外键走完，所以这里
        证明「任务确实跟着没了」—— 否则 publisher 会给一道不存在的题出题。
        """

        await self._create_testset_with_tasks("ts-task-6", [0])
        async with self._session_factory() as session:
            (entry,) = await SqlAlchemyEvalTaskRepository(session).list_pending(limit=10)

        async with self._session_factory() as session:
            await session.execute(
                text("DELETE FROM documents WHERE id = :doc"), {"doc": DOC_ID}
            )
            await session.commit()

        async with self._session_factory() as session:
            tasks = SqlAlchemyEvalTaskRepository(session)
            evals = SqlAlchemyEvalRepository(session)
            self.assertIsNone(await tasks.get(entry.id))
            self.assertEqual([], await tasks.list_pending(limit=10))
            self.assertEqual([], await evals.list_testset_items("ts-task-6"))
            self.assertIsNotNone(await evals.get_testset("ts-task-6"))

    async def test_list_pending_skip_locked_excludes_locked_rows(self) -> None:
        await self._create_testset_with_tasks("ts-task-5", [0])

        holder = self._session_factory()  # 事务 A：领取但不提交
        claimed = await SqlAlchemyEvalTaskRepository(holder).list_pending(limit=10)
        self.assertEqual(1, len(claimed))

        async with self._session_factory() as session:  # 事务 B：应跳过被锁的行
            tasks = SqlAlchemyEvalTaskRepository(session)
            self.assertEqual([], await tasks.list_pending(limit=10))

        await holder.commit()  # 释放锁
        await holder.close()

        async with self._session_factory() as session:
            tasks = SqlAlchemyEvalTaskRepository(session)
            self.assertEqual(1, len(await tasks.list_pending(limit=10)))


if __name__ == "__main__":
    unittest.main()
