"""EvalRepository 集成测试（需要本地 Postgres，连不上则跳过）。

覆盖测试集/条目的读写、派生进度、finalize_testset 的流转与幂等、reopen_testset、
证据表的坐标权威（ordinal 仅拼装序，平权无主）、evidence→documents 的 RESTRICT 防线，
以及 delete_items_referencing_document（0013 起「题随文档走」的唯一通道）。
事务由调用方（service / worker）控制：测试里 session.commit() 模拟提交点。

证据行带着 document_id 外键，所以坐标必须指向真实 documents 行 —— 每个用例
先备好一行 IT 文档，不然连 INSERT 都进不去。
"""

from __future__ import annotations

import unittest

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.domain.eval import (
    ChunkRef,
    EvalItemStatus,
    EvalRun,
    EvalRunItem,
    EvalRunStatus,
    TestSetStatus,
)
from app.infrastructure.postgres.eval_repository import SqlAlchemyEvalRepository

pytestmark = pytest.mark.integration

URL = "postgresql+asyncpg://rag:rag@127.0.0.1:5435/anna_rag"
DOC_ID = "it-eval-doc"
TS_ID = "ts-it-run"


def _refs(*chunk_indexes: int) -> list[ChunkRef]:
    return [
        ChunkRef(document_id=DOC_ID, chunk_index=index) for index in chunk_indexes
    ]


def _groups(*chunk_indexes: int) -> list[list[ChunkRef]]:
    """一块一元组：「一块一题」的旧形状。"""

    return [[ref] for ref in _refs(*chunk_indexes)]


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
class EvalRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def _delete_it_rows(self) -> None:
        # 删测试集就级联带走了它的题目；IT 文档独立一行，单独清
        async with self._session_factory() as session:
            await session.execute(text("DELETE FROM eval_testsets WHERE name LIKE 'IT测试集%'"))
            await session.execute(
                text("DELETE FROM documents WHERE id IN (:a, :b)"),
                {"a": DOC_ID, "b": "it-eval-doc-b"},
            )
            await session.commit()

    async def asyncSetUp(self) -> None:
        self._engine = create_async_engine(URL)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)
        await self._delete_it_rows()
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
        await self._delete_it_rows()
        await self._engine.dispose()

    async def _create(self, testset_id: str, refs: list[ChunkRef]) -> None:
        """建集 + 题目：一个事务（真实创建用例的形状）。

        这里传的是扁平坐标，每块包成一元组 = 「一块一题」的旧形状。
        """

        async with self._session_factory() as session:
            repo = SqlAlchemyEvalRepository(session)
            await repo.create_testset(testset_id=testset_id, name="IT测试集")
            await repo.add_testset_items(testset_id, [[ref] for ref in refs])
            await session.commit()

    async def _testset(self, testset_id: str):
        async with self._session_factory() as session:
            return await SqlAlchemyEvalRepository(session).get_testset(testset_id)

    async def _progress(self, testset_id: str) -> tuple[int, int]:
        ts = await self._testset(testset_id)
        return (ts.progress_done, ts.progress_total)

    async def _items(self, testset_id: str):
        async with self._session_factory() as session:
            return await SqlAlchemyEvalRepository(session).list_testset_items(testset_id)

    async def test_items_persist_coordinates_without_query(self) -> None:
        await self._create("ts-it-1", _refs(0, 1))

        items = await self._items("ts-it-1")

        self.assertEqual(2, len(items))
        self.assertEqual(EvalItemStatus.PENDING, items[0].status)
        self.assertIsNone(items[0].query)  # query 由 LLM worker 异步生成
        # 平权时代：坐标只在 evidence 列表，首块只是拼装序第一位
        self.assertEqual(DOC_ID, items[0].evidence[0].document_id)
        self.assertEqual(0, items[0].evidence[0].chunk_index)
        self.assertEqual(1, items[1].evidence[0].chunk_index)
        self.assertEqual(1, len(items[0].evidence))  # 一元组：一块就是全部证据

    async def test_primary_uniqueness_moved_to_the_service_layer(self) -> None:
        """0013 删了 (testset, 主坐标) 唯一约束：repo 层不再拦截同块两题。

        这不是漏洞而是口径搬家——去重由 EvalService.add_items 负责（单测覆盖）；
        这里锁住反面事实：绕过服务直写 repo 时 DB 不会炸，别让旧测试记忆
        在未来某天把它「修回去」。同时锁住 ordinal 唯一：一题的拼装序不许重号。
        """

        await self._create("ts-it-9", _refs(0))

        async with self._session_factory() as session:
            repo = SqlAlchemyEvalRepository(session)
            await repo.add_testset_items("ts-it-9", _groups(0))  # 同主坐标再来一题
            await session.commit()  # 不抛 —— 旧行为是 IntegrityError
        self.assertEqual(2, len(await self._items("ts-it-9")))

        async with self._session_factory() as session:
            items = await SqlAlchemyEvalRepository(session).list_testset_items("ts-it-9")
            item_id = items[0].id
            with self.assertRaises(IntegrityError):
                await session.execute(
                    text(
                        "INSERT INTO eval_testset_item_evidence"
                        " (item_id, document_id, chunk_index, ordinal)"
                        " VALUES (:i, :d, 5, 0)"  # 第二个 ordinal=0：撞 uq
                    ),
                    {"i": item_id, "d": DOC_ID},
                )
                await session.commit()

    async def test_progress_is_derived_from_item_status(self) -> None:
        await self._create("ts-it-2", _refs(0, 1))

        self.assertEqual((0, 2), await self._progress("ts-it-2"))

        async with self._session_factory() as session:
            repo = SqlAlchemyEvalRepository(session)
            items = await repo.list_testset_items("ts-it-2")
            await repo.set_item_result(items[0].id, query="每天吃多少苹果补维C？")
            await session.commit()

        # 一道成功 + 一道仍在生成：done 只数已进终态的
        self.assertEqual((1, 2), await self._progress("ts-it-2"))

        async with self._session_factory() as session:
            repo = SqlAlchemyEvalRepository(session)
            items = await repo.list_testset_items("ts-it-2")
            await repo.set_item_failed(items[1].id, error="llm down")
            await session.commit()

        # 失败条目也算 done：否则进度条永远差几格
        self.assertEqual((2, 2), await self._progress("ts-it-2"))

    async def test_finalize_waits_until_no_item_is_pending(self) -> None:
        await self._create("ts-it-3", _refs(0, 1))

        async with self._session_factory() as session:
            repo = SqlAlchemyEvalRepository(session)
            items = await repo.list_testset_items("ts-it-3")
            await repo.set_item_result(items[0].id, query="苹果有什么营养？")
            await repo.finalize_testset("ts-it-3")  # 还有一道 pending
            await session.commit()

        ts = await self._testset("ts-it-3")
        self.assertEqual(TestSetStatus.GENERATING, ts.status)

    async def test_finalize_leaves_an_empty_testset_generating(self) -> None:
        """建集与加题已拆开：空集是「刚建出来」而不是坏数据，不能流转成 failed。"""

        await self._create("ts-it-10", [])

        async with self._session_factory() as session:
            await SqlAlchemyEvalRepository(session).finalize_testset("ts-it-10")
            await session.commit()

        ts = await self._testset("ts-it-10")
        self.assertEqual(TestSetStatus.GENERATING, ts.status)
        self.assertEqual((0, 0), (ts.progress_done, ts.progress_total))

    async def test_finalize_ready_when_some_items_failed(self) -> None:
        """失败条目不阻塞收尾：只要没有 pending 就流转，失败数进 error_message。"""

        await self._create("ts-it-4", _refs(0, 1))

        async with self._session_factory() as session:
            repo = SqlAlchemyEvalRepository(session)
            items = await repo.list_testset_items("ts-it-4")
            await repo.set_item_result(items[0].id, query="苹果有什么营养？")
            await repo.set_item_failed(items[1].id, error="LLM 返回了空问题")
            await repo.finalize_testset("ts-it-4")
            await session.commit()

        ts = await self._testset("ts-it-4")
        self.assertEqual(TestSetStatus.READY, ts.status)
        self.assertEqual("1 项生成失败", ts.error_message)

    async def test_finalize_failed_when_no_item_generated(self) -> None:
        await self._create("ts-it-5", _refs(0))

        async with self._session_factory() as session:
            repo = SqlAlchemyEvalRepository(session)
            (item,) = await repo.list_testset_items("ts-it-5")
            await repo.set_item_failed(item.id, error="llm down")
            await repo.finalize_testset("ts-it-5")
            await session.commit()

        ts = await self._testset("ts-it-5")
        self.assertEqual(TestSetStatus.FAILED, ts.status)
        self.assertEqual("1 项生成失败", ts.error_message)

    async def test_finalize_is_idempotent_and_repeatable(self) -> None:
        await self._create("ts-it-6", _refs(0))

        async with self._session_factory() as session:
            repo = SqlAlchemyEvalRepository(session)
            items = await repo.list_testset_items("ts-it-6")
            await repo.set_item_result(items[0].id, query="苹果有什么营养？")
            await repo.finalize_testset("ts-it-6")
            await session.commit()

        # 再调一次（模拟并发里后到的 worker / redelivery）：状态不变
        async with self._session_factory() as session:
            await SqlAlchemyEvalRepository(session).finalize_testset("ts-it-6")
            await session.commit()

        ts = await self._testset("ts-it-6")
        self.assertEqual(TestSetStatus.READY, ts.status)
        self.assertIsNone(ts.error_message)

    async def test_reopen_returns_a_finished_testset_to_generating(self) -> None:
        """加新题前要把集退回 generating，否则列表上还显示上一批的 ready + 旧错误。"""

        await self._create("ts-it-11", _refs(0))
        async with self._session_factory() as session:
            repo = SqlAlchemyEvalRepository(session)
            (item,) = await repo.list_testset_items("ts-it-11")
            await repo.set_item_failed(item.id, error="llm down")
            await repo.finalize_testset("ts-it-11")
            await session.commit()
        self.assertEqual(TestSetStatus.FAILED, (await self._testset("ts-it-11")).status)

        async with self._session_factory() as session:
            await SqlAlchemyEvalRepository(session).reopen_testset("ts-it-11")
            await session.commit()

        ts = await self._testset("ts-it-11")
        self.assertEqual(TestSetStatus.GENERATING, ts.status)
        self.assertIsNone(ts.error_message)

    async def test_list_testsets_carries_derived_progress(self) -> None:
        await self._create("ts-it-7", _refs(0, 1))
        async with self._session_factory() as session:
            repo = SqlAlchemyEvalRepository(session)
            items = await repo.list_testset_items("ts-it-7")
            await repo.set_item_result(items[0].id, query="苹果有什么营养？")
            await session.commit()

        async with self._session_factory() as session:
            rows = await SqlAlchemyEvalRepository(session).list_testsets()

        target = next(row for row in rows if row.id == "ts-it-7")
        self.assertEqual(2, target.progress_total)
        self.assertEqual(1, target.progress_done)

    async def test_delete_testset_cascades(self) -> None:
        await self._create("ts-it-8", _refs(0))

        async with self._session_factory() as session:
            await SqlAlchemyEvalRepository(session).delete_testset("ts-it-8")
            await session.commit()

        async with self._session_factory() as session:
            repo = SqlAlchemyEvalRepository(session)
            self.assertIsNone(await repo.get_testset("ts-it-8"))
            self.assertEqual([], await repo.list_testset_items("ts-it-8"))

    async def test_deleting_a_referenced_document_hits_the_restrict_fuse(self) -> None:
        """忘 purge 就删文档：RESTRICT 撞回来，而不是静默留僵尸题（0013 的防线）。"""

        await self._create("ts-it-12", _refs(0, 1))

        async with self._session_factory() as session:
            with self.assertRaises(IntegrityError):
                await session.execute(
                    text("DELETE FROM documents WHERE id = :doc"), {"doc": DOC_ID}
                )
                await session.commit()

        # 撞回来之后题和文档都原样：事务回滚，不是删一半
        self.assertEqual(2, len(await self._items("ts-it-12")))

    async def test_purge_then_delete_document_takes_the_items(self) -> None:
        """DocumentService.delete 的正路：同事务先 purge 再删 documents 行。"""

        await self._create("ts-it-12", _refs(0, 1))

        async with self._session_factory() as session:
            repo = SqlAlchemyEvalRepository(session)
            removed = await repo.delete_items_referencing_document(DOC_ID)
            await session.execute(
                text("DELETE FROM documents WHERE id = :doc"), {"doc": DOC_ID}
            )
            await session.commit()

        self.assertEqual(2, removed)
        self.assertEqual([], await self._items("ts-it-12"))
        # 集本身还在（它不欠文档什么），只是进度归零
        ts = await self._testset("ts-it-12")
        self.assertEqual((0, 0), (ts.progress_done, ts.progress_total))

    async def test_item_without_a_document_is_rejected(self) -> None:
        async with self._session_factory() as session:
            repo = SqlAlchemyEvalRepository(session)
            await repo.create_testset(testset_id="ts-it-13", name="IT测试集")
            with self.assertRaises(IntegrityError):
                await repo.add_testset_items(
                    "ts-it-13",
                    [[ChunkRef(document_id="no-such-doc", chunk_index=0)]],
                )
                await session.flush()

    async def test_get_missing_returns_none(self) -> None:
        async with self._session_factory() as session:
            repo = SqlAlchemyEvalRepository(session)
            self.assertIsNone(await repo.get_testset("nope"))
            self.assertIsNone(await repo.get_item("nope"))

    async def test_multi_evidence_group_writes_full_projection(self) -> None:
        """一组三块（跨文档）= 一题：证据行平权，读回来完整有序。"""

        doc_b = "it-eval-doc-b"
        async with self._session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO documents (id, name, storage_key, size_bytes,"
                    " checksum_sha256, status) VALUES (:id, 'IT文档B', :key, 1, 'sha',"
                    " 'success')"
                ),
                {"id": doc_b, "key": f"{doc_b}.txt"},
            )
            repo = SqlAlchemyEvalRepository(session)
            await repo.create_testset(testset_id="ts-it-ev", name="IT测试集")
            await repo.add_testset_items(
                "ts-it-ev",
                [[_refs(0)[0], ChunkRef(document_id=doc_b, chunk_index=7), _refs(0)[0]]],
            )
            await session.commit()

        try:
            async with self._session_factory() as session:
                repo = SqlAlchemyEvalRepository(session)
                items = await repo.list_testset_items("ts-it-ev")
                self.assertEqual(1, len(items))
                # 顺序即入参序；组内重复坐标被去重；证据行是完整平权坐标
                self.assertEqual(
                    [(DOC_ID, 0), (doc_b, 7)],
                    [(r.document_id, r.chunk_index) for r in items[0].evidence_refs()],
                )
                single = await repo.get_item(items[0].id)
                self.assertIsNotNone(single)
                assert single is not None
                self.assertEqual(
                    [(DOC_ID, 0), (doc_b, 7)],
                    [(r.document_id, r.chunk_index) for r in single.evidence],
                )
        finally:
            async with self._session_factory() as session:
                await session.execute(text("DELETE FROM eval_testsets WHERE id = 'ts-it-ev'"))
                await session.execute(
                    text("DELETE FROM documents WHERE id = :id"), {"id": doc_b}
                )
                await session.commit()

    async def test_purge_items_referencing_document_catches_evidence_only(self) -> None:
        """证据文档消失 → 整题被清（主文档的 FK CASCADE 覆盖不到这条通道）。"""

        doc_b = "it-eval-doc-b"
        async with self._session_factory() as session:
            await session.execute(
                text(
                    "INSERT INTO documents (id, name, storage_key, size_bytes,"
                    " checksum_sha256, status) VALUES (:id, 'IT文档B', :key, 1, 'sha',"
                    " 'success')"
                ),
                {"id": doc_b, "key": f"{doc_b}.txt"},
            )
            repo = SqlAlchemyEvalRepository(session)
            await repo.create_testset(testset_id="ts-it-purge", name="IT测试集")
            await repo.add_testset_items(
                "ts-it-purge",
                [*_groups(0), [_refs(1)[0], ChunkRef(document_id=doc_b, chunk_index=0)]],
            )
            await session.commit()

        try:
            async with self._session_factory() as session:
                repo = SqlAlchemyEvalRepository(session)
                # 删的是 doc_b：只有第二题把它当证据
                removed = await repo.delete_items_referencing_document(doc_b)
                await session.execute(
                    text("DELETE FROM documents WHERE id = :id"), {"id": doc_b}
                )
                await session.commit()
                self.assertEqual(1, removed)
            async with self._session_factory() as session:
                left = await SqlAlchemyEvalRepository(session).list_testset_items(
                    "ts-it-purge"
                )
                self.assertEqual(1, len(left))
                self.assertEqual(0, left[0].evidence[0].chunk_index)
        finally:
            async with self._session_factory() as session:
                await session.execute(text("DELETE FROM eval_testsets WHERE id = 'ts-it-purge'"))
                await session.commit()

    async def test_set_item_on_missing_raises_keyerror(self) -> None:
        async with self._session_factory() as session:
            repo = SqlAlchemyEvalRepository(session)
            with self.assertRaises(KeyError):
                await repo.set_item_result("nope", query="x")


def _run_tables_alive() -> bool:
    """eval_runs 建了没有（0008 还没跑就整个类跳过，而不是全红）。"""

    try:
        import asyncio

        async def _check() -> bool:
            engine = create_async_engine(URL, pool_pre_ping=True, connect_args={"timeout": 3})
            try:
                async with engine.connect() as conn:
                    tables = (
                        await conn.execute(
                            text(
                                "SELECT to_regclass('public.eval_runs'),"
                                " to_regclass('public.eval_run_items')"
                            )
                        )
                    ).one()
            finally:
                await engine.dispose()
            return all(name is not None for name in tables)

        return asyncio.run(_check())
    except Exception:
        return False


@unittest.skipUnless(_postgres_alive(), f"本地 Postgres 不可用: {URL}")
@unittest.skipUnless(_run_tables_alive(), "eval_runs 表不存在（先 alembic upgrade head）")
class EvalRunRepositoryTests(unittest.IsolatedAsyncioTestCase):
    """run 与逐题结果：配置快照、派生进度、一次性收尾、级联。"""

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
            # 两道已出好的题 + 一道出坏的题（run 只该看到前两道）
            await SqlAlchemyEvalRepository(session).create_testset(
                testset_id=TS_ID, name="IT测试集run"
            )
            await SqlAlchemyEvalRepository(session).add_testset_items(
                TS_ID, _groups(0, 1, 2)
            )
            await session.commit()
        async with self._session_factory() as session:
            repo = SqlAlchemyEvalRepository(session)
            items = await repo.list_testset_items(TS_ID)
            await repo.set_item_result(items[0].id, query="豆腐有多少蛋白质？")
            await repo.set_item_result(items[1].id, query="抗生素能治病毒吗？")
            await repo.set_item_failed(items[2].id, error="llm down")
            await session.commit()

    async def asyncTearDown(self) -> None:
        await self._cleanup()
        await self._engine.dispose()

    async def _cleanup(self) -> None:
        # eval_runs 对 testset 是 CASCADE，删集就带走了它的全部 run 与结果
        async with self._session_factory() as session:
            await session.execute(
                text("DELETE FROM eval_testsets WHERE id = :ts"), {"ts": TS_ID}
            )
            await session.execute(text("DELETE FROM documents WHERE id = :doc"), {"doc": DOC_ID})
            await session.commit()

    async def _create_run(self, run_id: str, *, config: dict | None = None) -> None:
        async with self._session_factory() as session:
            await SqlAlchemyEvalRepository(session).create_run(
                run_id=run_id, testset_id=TS_ID, config=config or {"top_k": 5}
            )
            await session.commit()

    async def _item_ids(self) -> list[str]:
        async with self._session_factory() as session:
            items = await SqlAlchemyEvalRepository(session).list_testset_items(TS_ID)
        return [item.id for item in items]

    async def _record(self, run_id: str, item_id: str, **kwargs) -> None:
        result = EvalRunItem(
            testset_item_id=item_id,
            query="占位：结果表不存题面",
            hit_rank=kwargs.get("hit_rank", 1),
            latency_ms=kwargs.get("latency_ms", 12.5),
            evidence_total=kwargs.get("evidence_total", 1),
            evidence_matched=kwargs.get("evidence_matched", 0),
            evidence_ranks=kwargs.get("evidence_ranks"),
        )
        async with self._session_factory() as session:
            await SqlAlchemyEvalRepository(session).record_run_item(run_id, result)
            await session.commit()

    async def _run(self, run_id: str) -> EvalRun | None:
        async with self._session_factory() as session:
            return await SqlAlchemyEvalRepository(session).get_run(run_id)

    async def test_run_starts_running_with_its_config_and_no_results(self) -> None:
        await self._create_run("run-it-1", config={"top_k": 3, "query_rewrite": False})

        run = await self._run("run-it-1")

        self.assertEqual(EvalRunStatus.RUNNING, run.status)
        self.assertEqual({"top_k": 3, "query_rewrite": False}, run.config)
        self.assertIsNone(run.metrics)
        self.assertIsNone(run.finished_at)
        # 分母只数 ready：那道出坏的题不在任何 run 的范围里
        self.assertEqual((0, 2), (run.progress_done, run.progress_total))

    async def test_progress_is_derived_from_result_rows(self) -> None:
        await self._create_run("run-it-2")
        first, second = (await self._item_ids())[:2]

        await self._record("run-it-2", first)

        self.assertEqual(1, (await self._run("run-it-2")).progress_done)
        await self._record("run-it-2", second)
        self.assertEqual(2, (await self._run("run-it-2")).progress_done)

    async def test_results_carry_the_question_without_storing_a_copy(self) -> None:
        """结果表只有坐标引用：题面与期望坐标都从 eval_testset_items 联查出来。"""

        await self._create_run("run-it-3")
        item_id = (await self._item_ids())[1]

        await self._record(
            "run-it-3", item_id, hit_rank=2, latency_ms=7.0,
            evidence_total=1, evidence_matched=1, evidence_ranks=[2],
        )

        (result,) = await self._run_items("run-it-3")
        self.assertEqual("抗生素能治病毒吗？", result.query)
        self.assertEqual(2, result.hit_rank)
        self.assertEqual([2], result.evidence_ranks)  # JSONB 名次快照 round-trip
        self.assertAlmostEqual(0.5, result.average_precision)  # 单证据：1/rank
        self.assertEqual(1, result.joint_hit)  # 派生自 evidence_matched>=total

    async def test_one_question_can_only_be_scored_once_per_run(self) -> None:
        await self._create_run("run-it-4")
        item_id = (await self._item_ids())[0]
        await self._record("run-it-4", item_id)

        async with self._session_factory() as session:
            with self.assertRaises(IntegrityError):
                await SqlAlchemyEvalRepository(session).record_run_item(
                    "run-it-4",
                    EvalRunItem(
                        testset_item_id=item_id,
                        query="重复写",
                        hit_rank=1,
                        latency_ms=1.0,
                    ),
                )
                await session.flush()

    async def test_unscored_questions_are_the_ready_ones_minus_scored(self) -> None:
        await self._create_run("run-it-5")

        questions = await self._unscored("run-it-5")
        self.assertEqual(2, len(questions))  # 出坏的那道不算

        await self._record("run-it-5", questions[0].id)

        rest = await self._unscored("run-it-5")
        self.assertEqual([questions[1].id], [question.id for question in rest])

    async def test_finish_run_is_a_one_shot_conditional_write(self) -> None:
        """重复收尾（或和启动扫撞上）不能把已终态的 run 改回去，也不能改时间。"""

        await self._create_run("run-it-6")
        async with self._session_factory() as session:
            await SqlAlchemyEvalRepository(session).finish_run(
                "run-it-6", status=EvalRunStatus.DONE, metrics={"recall@5": 1.0}
            )
            await session.commit()
        finished_at = (await self._run("run-it-6")).finished_at

        async with self._session_factory() as session:
            await SqlAlchemyEvalRepository(session).finish_run(
                "run-it-6", status=EvalRunStatus.FAILED, error_message="later"
            )
            await session.commit()

        run = await self._run("run-it-6")
        self.assertEqual(EvalRunStatus.DONE, run.status)
        self.assertEqual({"recall@5": 1.0}, run.metrics)
        self.assertIsNone(run.error_message)
        self.assertEqual(finished_at, run.finished_at)

    async def test_finalize_run_waits_while_tasks_are_open(self) -> None:
        await self._create_run("run-it-7")

        async with self._session_factory() as session:
            await SqlAlchemyEvalRepository(session).finalize_run(
                "run-it-7", pending_open=1, failed=0
            )
            await session.commit()

        run = await self._run("run-it-7")
        self.assertEqual(EvalRunStatus.RUNNING, run.status)
        self.assertIsNone(run.finished_at)

    async def test_finalize_run_aggregates_done_metrics(self) -> None:
        await self._create_run("run-it-8")
        item_ids = await self._item_ids()
        await self._record(
            "run-it-8", item_ids[0], hit_rank=1, latency_ms=10.0,
            evidence_matched=1, evidence_ranks=[1],
        )
        await self._record("run-it-8", item_ids[1], hit_rank=None, latency_ms=30.0)

        async with self._session_factory() as session:
            await SqlAlchemyEvalRepository(session).finalize_run(
                "run-it-8", pending_open=0, failed=0
            )
            await session.commit()

        run = await self._run("run-it-8")
        self.assertEqual(EvalRunStatus.DONE, run.status)
        # 指标从库里的结果行算：一中一不中 -> 0.5；延迟 10/30 -> 20
        self.assertEqual(0.5, run.metrics["recall@5"])  # 块级全在：一中一空
        self.assertEqual(0.5, run.metrics["map@5"])  # 第 1 名 1.0 + 全落空 0.0
        self.assertEqual(20.0, run.metrics["avg_latency_ms"])
        self.assertEqual(2, run.metrics["queries"])

        # 重入 finalize：条件写对已终态的 run 是空操作，finished_at 只有一个值
        finished_at = run.finished_at
        async with self._session_factory() as session:
            await SqlAlchemyEvalRepository(session).finalize_run(
                "run-it-8", pending_open=0, failed=0
            )
            await session.commit()
        again = await self._run("run-it-8")
        self.assertEqual(EvalRunStatus.DONE, again.status)
        self.assertEqual(finished_at, again.finished_at)

    async def test_finalize_run_reports_failed_count_instead_of_partial_metrics(self) -> None:
        """有题永久失败时宁可 FAILED 也不发布「小分母冒充完整评测」的指标。"""

        await self._create_run("run-it-9")
        item_ids = await self._item_ids()
        await self._record("run-it-9", item_ids[0])

        async with self._session_factory() as session:
            await SqlAlchemyEvalRepository(session).finalize_run(
                "run-it-9", pending_open=0, failed=1
            )
            await session.commit()

        run = await self._run("run-it-9")
        self.assertEqual(EvalRunStatus.FAILED, run.status)
        self.assertEqual("1 道题评测失败", run.error_message)
        self.assertIsNone(run.metrics)
        # 已写出的那行结果仍在：明细可查，只是不聚合冒充完整评测
        self.assertEqual(1, len(await self._run_items("run-it-9")))

    async def test_has_run_result_tracks_stored_rows(self) -> None:
        await self._create_run("run-it-10")
        item_ids = await self._item_ids()
        async with self._session_factory() as session:
            repo = SqlAlchemyEvalRepository(session)
            self.assertFalse(await repo.has_run_result("run-it-10", item_ids[0]))
        await self._record("run-it-10", item_ids[0])
        async with self._session_factory() as session:
            repo = SqlAlchemyEvalRepository(session)
            self.assertTrue(await repo.has_run_result("run-it-10", item_ids[0]))
            self.assertFalse(await repo.has_run_result("run-it-10", item_ids[1]))

    async def test_list_runs_is_newest_first_with_progress(self) -> None:
        await self._create_run("run-it-9")
        async with self._session_factory() as session:
            await SqlAlchemyEvalRepository(session).finish_run(
                "run-it-9", status=EvalRunStatus.DONE, metrics={}
            )
            await session.commit()
        await self._create_run("run-it-10")
        await self._record("run-it-10", (await self._item_ids())[0])

        async with self._session_factory() as session:
            runs = await SqlAlchemyEvalRepository(session).list_runs(TS_ID)

        self.assertEqual(["run-it-10", "run-it-9"], [run.id for run in runs])
        self.assertEqual((1, 2), (runs[0].progress_done, runs[0].progress_total))
        self.assertEqual((0, 2), (runs[1].progress_done, runs[1].progress_total))
        async with self._session_factory() as session:
            self.assertEqual(
                [], await SqlAlchemyEvalRepository(session).list_runs("no-such-ts")
            )

    async def test_deleting_the_testset_takes_its_runs(self) -> None:
        await self._create_run("run-it-11")
        await self._record("run-it-11", (await self._item_ids())[0])

        async with self._session_factory() as session:
            await SqlAlchemyEvalRepository(session).delete_testset(TS_ID)
            await session.commit()

        self.assertIsNone(await self._run("run-it-11"))
        async with self._session_factory() as session:
            count = (
                await session.execute(
                    text("SELECT count(*) FROM eval_run_items WHERE run_id = 'run-it-11'")
                )
            ).scalar_one()
        self.assertEqual(0, count)

    async def test_deleting_the_document_drops_the_question_and_its_result(self) -> None:
        """purge 文档引用题（0013 唯一通道），它的 run 结果也一起走：留下就对不上被问的东西。

        run 行本身还在，metrics_json 还是跑完那一刻的聚合数 —— 逐题明细少了几条，
        但历史指标的口径不回溯修改。
        """

        await self._create_run("run-it-12")
        item_id = (await self._item_ids())[0]
        await self._record("run-it-12", item_id)

        async with self._session_factory() as session:
            await SqlAlchemyEvalRepository(session).delete_items_referencing_document(DOC_ID)
            await session.execute(
                text("DELETE FROM documents WHERE id = :doc"), {"doc": DOC_ID}
            )
            await session.commit()

        self.assertEqual([], await self._run_items("run-it-12"))
        self.assertIsNotNone(await self._run("run-it-12"))
        # 三道题都指向这个文档，purge 之后一道都不剩
        self.assertEqual([], await self._unscored("run-it-12"))

    async def test_run_of_a_missing_run_reads_as_none(self) -> None:
        self.assertIsNone(await self._run("nope"))
        async with self._session_factory() as session:
            repo = SqlAlchemyEvalRepository(session)
            self.assertEqual([], await repo.list_run_items("nope"))
            self.assertEqual([], await repo.list_unscored_questions("nope"))
            with self.assertRaises(IntegrityError):
                await repo.record_run_item(
                    "nope",
                    EvalRunItem(
                        testset_item_id=(await self._item_ids())[0],
                        query="x",
                        hit_rank=1,
                        latency_ms=1.0,
                    ),
                )
                await session.flush()

    async def _run_items(self, run_id: str):
        async with self._session_factory() as session:
            return await SqlAlchemyEvalRepository(session).list_run_items(run_id)

    async def _unscored(self, run_id: str):
        async with self._session_factory() as session:
            return await SqlAlchemyEvalRepository(session).list_unscored_questions(run_id)


if __name__ == "__main__":
    unittest.main()
