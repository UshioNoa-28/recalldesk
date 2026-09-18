"""graph_tasks 出箱仓储的集成测试（真 Postgres，连不上自动跳过）。

覆盖手动重跑的三态：在途拒绝 / 终态复位 / 无历史新建，外加 latest_for_document_ids。
"""

from __future__ import annotations

import unittest

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.infrastructure.postgres.graph_task_repository import SqlAlchemyGraphTaskRepository

pytestmark = pytest.mark.integration

URL = "postgresql+asyncpg://rag:rag@127.0.0.1:5435/anna_rag"
DOC = "it-graph-task-doc"


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


@unittest.skipUnless(_postgres_alive(), f"本地 Postgres 不可用: {URL}")
class GraphTaskRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._engine = create_async_engine(URL)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)
        await self._cleanup()
        async with self._session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO documents (id, name, storage_key, size_bytes,"
                    " checksum_sha256, status) VALUES (:id, 'IT图档', :key, 1, 'sha',"
                    " 'success')"
                ),
                {"id": DOC, "key": f"{DOC}.txt"},
            )
            await session.commit()

    async def _cleanup(self) -> None:
        async with self._session_factory() as session:
            await session.execute(
                text("DELETE FROM graph_tasks WHERE document_id = :d"), {"d": DOC}
            )
            await session.execute(text("DELETE FROM documents WHERE id = :d"), {"d": DOC})
            await session.commit()

    async def asyncTearDown(self) -> None:
        await self._cleanup()
        await self._engine.dispose()

    async def _repo(self, session):
        return SqlAlchemyGraphTaskRepository(session, retry_backoff_seconds=30.0)

    async def test_first_queue_extraction_creates_and_inflight_refuses(self) -> None:
        async with self._session_factory() as session:
            repo = await self._repo(session)
            self.assertEqual("created", await repo.queue_extraction(DOC))
            await session.commit()

        async with self._session_factory() as session:
            repo = await self._repo(session)
            with self.assertRaises(ValueError):  # 在途不排队套排队
                await repo.queue_extraction(DOC)

    async def test_failed_resets_in_place_and_latest_map_sees_it(self) -> None:
        async with self._session_factory() as session:
            repo = await self._repo(session)
            await repo.queue_extraction(DOC)
            await session.commit()
        async with self._session_factory() as session:
            repo = await self._repo(session)
            pending = await repo.list_pending(limit=1)
            await repo.record_failure(pending[0].id, error="llm down")
            await repo.mark_failed(pending[0].id)
            await session.commit()
        async with self._session_factory() as session:
            repo = await self._repo(session)
            latest = await repo.latest_for_document_ids([DOC])
            self.assertEqual("failed", latest[DOC][0])
            self.assertEqual("requeued", await repo.queue_extraction(DOC))
            after = await repo.latest_for_document_ids([DOC])
            self.assertEqual("pending", after[DOC][0])
            self.assertIsNone(after[DOC][1])
            await session.commit()

    async def test_latest_map_skips_documents_without_tasks(self) -> None:
        async with self._session_factory() as session:
            repo = await self._repo(session)
            self.assertEqual({}, await repo.latest_for_document_ids(["ghost-doc"]))
