"""EvalRunTaskRepository 集成测试（需要本地 Postgres，连不上则跳过）。

只管任务表：领取 / 标记 / 退避 / 计数 / 级联。
收尾（finalize_run）读的是「调用方传进来的计数」，归 test_eval_repository.py。
"""

from __future__ import annotations

import unittest

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.domain.eval import ChunkRef, EvalRunStatus, EvalTaskStatus
from app.infrastructure.postgres.eval_repository import SqlAlchemyEvalRepository
from app.infrastructure.postgres.eval_run_task_repository import SqlAlchemyEvalRunTaskRepository

pytestmark = pytest.mark.integration

URL = "postgresql+asyncpg://rag:rag@127.0.0.1:5435/anna_rag"
DOC_ID = "it-run-task-doc"


def _postgres_alive() -> bool:
    try:
        import asyncio

        async def _ping() -> bool:
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


def _run_tasks_alive() -> bool:
    """eval_run_tasks 建了没有（0012 还没跑就整个类跳过，而不是全红）。"""

    try:
        import asyncio

        async def _check() -> bool:
            engine = create_async_engine(URL, pool_pre_ping=True, connect_args={"timeout": 3})
            try:
                async with engine.connect() as conn:
                    table = (
                        await conn.execute(
                            text("SELECT to_regclass('public.eval_run_tasks')")
                        )
                    ).scalar()
            finally:
                await engine.dispose()
            return table is not None

        return asyncio.run(_check())
    except Exception:
        return False


@unittest.skipUnless(_postgres_alive(), f"本地 Postgres 不可用: {URL}")
@unittest.skipUnless(_run_tasks_alive(), "eval_run_tasks 表不存在（先 alembic upgrade head）")
class EvalRunTaskRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._engine = create_async_engine(URL)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)
        await self._cleanup()
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

    async def asyncTearDown(self) -> None:
        await self._cleanup()
        await self._engine.dispose()

    async def _cleanup(self) -> None:
        async with self._session_factory() as session:
            await session.execute(
                text("DELETE FROM eval_testsets WHERE name LIKE 'IT逐题集%'")
            )
            await session.execute(text("DELETE FROM documents WHERE id = :doc"), {"doc": DOC_ID})
            await session.commit()

    async def _seed(self, run_id: str, chunk_indexes: list[int]) -> list[str]:
        """建集 + 题目 + run + 每题一条任务：单个事务（真实 start_run 的形状）。"""

        async with self._session_factory() as session:
            evals = SqlAlchemyEvalRepository(session)
            tasks = SqlAlchemyEvalRunTaskRepository(session)
            await evals.create_testset(testset_id=run_id, name=f"IT逐题集-{run_id}")
            await evals.add_testset_items(
                run_id,
                [[ChunkRef(document_id=DOC_ID, chunk_index=index)] for index in chunk_indexes],
            )
            for item in await evals.list_testset_items(run_id):
                await evals.set_item_result(item.id, query=f"问题{item.evidence[0].chunk_index}")
            await evals.create_run(
                run_id=run_id, testset_id=run_id, config={"top_k": 5}
            )
            items = await evals.list_testset_items(run_id)
            for item in items:
                await tasks.add(run_id=run_id, item_id=item.id)
            await session.commit()
            return [item.id for item in items]

    async def test_claim_then_queue_then_success(self) -> None:
        await self._seed("run-task-1", [0, 1])

        async with self._session_factory() as session:
            tasks = SqlAlchemyEvalRunTaskRepository(session)
            pending = await tasks.list_pending(limit=10)
            self.assertEqual(2, len(pending))
            self.assertTrue(all(t.status is EvalTaskStatus.PENDING for t in pending))
            await tasks.mark_queued(pending[0].id)
            await session.commit()
            task_id = pending[0].id

        async with self._session_factory() as session:
            tasks = SqlAlchemyEvalRunTaskRepository(session)
            # QUEUE 不再被领取；另一条还在
            rest = await tasks.list_pending(limit=10)
            self.assertEqual([p.id for p in rest if p.id != task_id], [t.id for t in rest])
            await tasks.mark_success(task_id)
            await session.commit()

        async with self._session_factory() as session:
            task = await SqlAlchemyEvalRunTaskRepository(session).get(task_id)
            self.assertEqual(EvalTaskStatus.SUCCESS, task.status)
            self.assertIsNotNone(task.queued_at)

    async def test_record_failure_backs_off(self) -> None:
        await self._seed("run-task-2", [0])

        async with self._session_factory() as session:
            tasks = SqlAlchemyEvalRunTaskRepository(session)
            (entry,) = await tasks.list_pending(limit=10)
            await tasks.record_failure(entry.id, error="neo4j down")
            await session.commit()

        async with self._session_factory() as session:
            tasks = SqlAlchemyEvalRunTaskRepository(session)
            self.assertEqual([], await tasks.list_pending(limit=10))  # 退避期内不可领
            task = await tasks.get(entry.id)
            self.assertEqual(EvalTaskStatus.PENDING, task.status)
            self.assertEqual(1, task.attempts)
            self.assertEqual("neo4j down", task.last_error)

        async with self._session_factory() as session:
            await session.execute(
                text("UPDATE eval_run_tasks SET next_retry_at = now() - interval '1 second'")
            )
            await session.commit()

        async with self._session_factory() as session:
            tasks = SqlAlchemyEvalRunTaskRepository(session)
            self.assertEqual(
                [entry.id], [t.id for t in await tasks.list_pending(limit=10)]
            )

    async def test_count_by_status_groups_the_run(self) -> None:
        await self._seed("run-task-3", [0, 1, 2])

        async with self._session_factory() as session:
            tasks = SqlAlchemyEvalRunTaskRepository(session)
            pending = await tasks.list_pending(limit=10)
            await tasks.mark_queued(pending[0].id)
            await tasks.mark_success(pending[0].id)
            await tasks.record_failure(pending[1].id, error="boom")
            await tasks.mark_failed(pending[1].id)
            counts = await tasks.count_by_status("run-task-3")
            await session.commit()

        self.assertEqual(1, counts.get("success"))
        self.assertEqual(1, counts.get("failed"))
        self.assertEqual(1, counts.get("pending"))

    async def test_one_task_per_item_per_run(self) -> None:
        await self._seed("run-task-4", [0])
        async with self._session_factory() as session:
            tasks = SqlAlchemyEvalRunTaskRepository(session)
            (entry,) = await tasks.list_pending(limit=10)
            with self.assertRaises(IntegrityError):
                await tasks.add(run_id="run-task-4", item_id=entry.item_id)
                await session.flush()

    async def test_deleting_the_testset_takes_runs_and_tasks(self) -> None:
        """testset -> run -> task 级联：publisher/consumer 都不该摸到孤儿任务。"""

        await self._seed("run-task-5", [0, 1])
        async with self._session_factory() as session:
            await session.execute(
                text("DELETE FROM eval_testsets WHERE id = :ts"), {"ts": "run-task-5"}
            )
            await session.commit()

        async with self._session_factory() as session:
            tasks = SqlAlchemyEvalRunTaskRepository(session)
            self.assertEqual([], await tasks.list_pending(limit=10))

    async def test_run_row_starts_running_and_reuses_task_status_enum(self) -> None:
        """冒烟：create_run 与任务行同事务提交后，run 处于 running、任务全 PENDING。"""

        await self._seed("run-task-6", [0])
        async with self._session_factory() as session:
            run = await SqlAlchemyEvalRepository(session).get_run("run-task-6")
            counts = await SqlAlchemyEvalRunTaskRepository(session).count_by_status(
                "run-task-6"
            )

        self.assertEqual(EvalRunStatus.RUNNING, run.status)
        self.assertEqual({"pending": 1}, counts)


if __name__ == "__main__":
    unittest.main()
