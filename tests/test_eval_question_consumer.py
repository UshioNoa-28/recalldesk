"""EvalQuestionConsumer 出题流程测试（fake queue / repos / generator / 向量库）。

覆盖：幂等守卫（redelivery 跳过）、按坐标回查素材后出题回写、失败重试与
超限终态、素材取不到或为空时直接终态、条目进终态必然流转测试集（finalize）、
commit 失败不 ACK。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import ClassVar
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from app.application.services.consume.eval_question_consumer import EvalQuestionConsumer
from app.domain.eval import EvalItemStatus, EvalTask, EvalTaskStatus, EvalTestSetItem
from settings import settings

_CONSUMER_MODULE = "app.application.services.consume.eval_question_consumer"


def _task(
    task_id: str = "task-1",
    status: EvalTaskStatus = EvalTaskStatus.QUEUE,
    attempts: int = 0,
) -> EvalTask:
    return EvalTask(
        id=task_id,
        testset_id="ts-1",
        item_id="item-1",
        status=status,
        attempts=attempts,
        last_error=None,
        created_at=datetime.now(UTC),
        queued_at=datetime.now(UTC),
    )


def _item(status: EvalItemStatus = EvalItemStatus.PENDING) -> EvalTestSetItem:
    return EvalTestSetItem(
        id="item-1",
        answer_document_id="doc-1",
        answer_chunk_index=0,
        status=status,
    )


def _chunk(text: str = "片段内容") -> dict:
    """Qdrant 里的那个分块点：出题素材的唯一来源。"""

    return {
        "point_id": "point-1",
        "document_name": "notes.md",
        "chunk_index": 0,
        "chunk_count": 1,
        "text": text,
    }


class FakeVectorRepository:
    """类级配置：chunk = None 表示点已经不在了（文档被删或重建过）。"""

    chunk: ClassVar[dict | None] = _chunk()
    reads: ClassVar[list[tuple[str, int]]] = []

    async def get_chunk(self, *, document_id: str, chunk_index: int) -> dict | None:
        type(self).reads.append((document_id, chunk_index))
        return type(self).chunk


class FakeSession:
    def __init__(self, commit_error: Exception | None = None) -> None:
        self.commit_error = commit_error
        self.commits = 0

    async def commit(self) -> None:
        if self.commit_error is not None:
            raise self.commit_error
        self.commits += 1


class _FakeSessionContext:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> FakeSession:
        return self._session

    async def __aexit__(self, *args) -> None:
        return None


class _FakeSessionFactory:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    def __call__(self) -> _FakeSessionContext:
        return _FakeSessionContext(self._session)


class FakeEvalTaskRepository:
    """模拟 eval_tasks 的读写；类级配置，实例记录调用。"""

    instances: ClassVar[list[FakeEvalTaskRepository]] = []
    task: ClassVar[EvalTask | None] = _task()  # None 表示任务不存在

    def __init__(self, session: FakeSession) -> None:
        self.session = session
        type(self).instances.append(self)

    async def get(self, task_id: str) -> EvalTask | None:
        task = type(self).task
        return task if task and task.id == task_id else None

    async def mark_success(self, task_id: str) -> None:
        task = type(self).task
        if task is None:
            raise KeyError(task_id)
        task.status = EvalTaskStatus.SUCCESS

    async def record_failure(self, task_id: str, *, error: str) -> None:
        task = type(self).task
        if task is None:
            raise KeyError(task_id)
        task.attempts += 1
        task.status = EvalTaskStatus.PENDING  # 与真实仓储一致：失败回 PENDING 等重投
        task.last_error = error

    async def mark_failed(self, task_id: str) -> None:
        task = type(self).task
        if task is None:
            raise KeyError(task_id)
        task.status = EvalTaskStatus.FAILED


class FakeEvalRepository:
    """模拟 items / testset 的读写；类级配置，实例记录调用。"""

    instances: ClassVar[list[FakeEvalRepository]] = []
    item: ClassVar[EvalTestSetItem | None] = _item()  # None 表示条目不存在

    def __init__(self, session: FakeSession) -> None:
        self.session = session
        self.finalized: list[str] = []
        type(self).instances.append(self)

    async def get_item(self, item_id: str) -> EvalTestSetItem | None:
        item = type(self).item
        return item if item and item.id == item_id else None

    async def set_item_result(self, item_id: str, *, query: str) -> None:
        item = type(self).item
        if item is None:
            raise KeyError(item_id)
        item.query = query
        item.status = EvalItemStatus.READY

    async def set_item_failed(self, item_id: str, *, error: str) -> None:
        item = type(self).item
        if item is None:
            raise KeyError(item_id)
        item.status = EvalItemStatus.FAILED
        item.error_message = error

    async def finalize_testset(self, testset_id: str) -> None:
        self.finalized.append(testset_id)


class FakeQuestionGenerator:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.called_with: list[tuple[str, str]] = []

    async def generate(self, *, context_text: str, document_name: str) -> str:
        if self.error is not None:
            raise self.error
        self.called_with.append((context_text, document_name))
        return "什么是 RAG？"


class FakeQueue:
    def __init__(self) -> None:
        self.acked: list[str] = []

    async def enqueue(self, *, task_id: str, item_id: str) -> str:
        return "1-0"

    async def ensure_consumer_group(self) -> None:
        return None

    async def read_new(
        self, *, consumer_name: str, count: int, block_ms: int
    ) -> list[tuple[str, dict]]:
        return []

    async def ack(self, message_id: str) -> None:
        self.acked.append(message_id)

    async def claim_orphans(
        self, *, consumer_name: str, count: int
    ) -> list[tuple[str, dict]]:
        return []


def _build_consumer(
    generator: FakeQuestionGenerator | None = None,
    session: FakeSession | None = None,
    queue: FakeQueue | None = None,
    vectors: FakeVectorRepository | None = None,
) -> tuple[EvalQuestionConsumer, FakeQueue]:
    queue = queue or FakeQueue()
    consumer = EvalQuestionConsumer(
        queue=queue,
        session_factory=_FakeSessionFactory(session or FakeSession()),
        question_generator=generator or FakeQuestionGenerator(),
        vector_repository=vectors or FakeVectorRepository(),
    )
    return consumer, queue


class _RepoFixture(IsolatedAsyncioTestCase):
    """公共脚手架：替换两个仓储，每个用例拿到新状态。"""

    def setUp(self) -> None:
        FakeEvalTaskRepository.instances.clear()
        FakeEvalRepository.instances.clear()
        FakeEvalTaskRepository.task = _task()
        FakeEvalRepository.item = _item()
        FakeVectorRepository.chunk = _chunk()
        FakeVectorRepository.reads.clear()
        patcher = patch.multiple(
            _CONSUMER_MODULE,
            SqlAlchemyEvalTaskRepository=FakeEvalTaskRepository,
            SqlAlchemyEvalRepository=FakeEvalRepository,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def evals(self) -> FakeEvalRepository:
        return FakeEvalRepository.instances[0]


class EvalQuestionConsumerHandleTaskTests(_RepoFixture):
    async def test_success_writes_item_marks_task_and_finalizes(self) -> None:
        generator = FakeQuestionGenerator()
        consumer, _ = _build_consumer(generator)

        await consumer._handle_task(task_id="task-1", item_id="item-1")

        task = FakeEvalTaskRepository.task
        item = FakeEvalRepository.item
        self.assertEqual(EvalTaskStatus.SUCCESS, task.status)
        self.assertEqual(EvalItemStatus.READY, item.status)
        self.assertEqual("什么是 RAG？", item.query)
        self.assertEqual(["ts-1"], self.evals().finalized)
        self.assertEqual([("doc-1", 0)], FakeVectorRepository.reads)
        self.assertEqual([("片段内容", "notes.md")], generator.called_with)

    async def test_redelivery_of_finished_task_skips_llm(self) -> None:
        FakeEvalTaskRepository.task = _task(status=EvalTaskStatus.SUCCESS)
        generator = FakeQuestionGenerator()
        consumer, _ = _build_consumer(generator)

        await consumer._handle_task(task_id="task-1", item_id="item-1")

        self.assertEqual([], generator.called_with)  # 幂等：不重复调 LLM
        self.assertEqual([], FakeVectorRepository.reads)  # 素材也不用再读一次
        self.assertEqual([], self.evals().finalized)  # 任务已终态，不再收尾

    async def test_item_already_ready_finalizes_anyway(self) -> None:
        FakeEvalRepository.item = _item(status=EvalItemStatus.READY)
        generator = FakeQuestionGenerator()
        consumer, _ = _build_consumer(generator)

        await consumer._handle_task(task_id="task-1", item_id="item-1")

        self.assertEqual([], generator.called_with)
        self.assertEqual(EvalTaskStatus.SUCCESS, FakeEvalTaskRepository.task.status)
        self.assertEqual(["ts-1"], self.evals().finalized)

    async def test_missing_task_is_noop(self) -> None:
        FakeEvalTaskRepository.task = None
        generator = FakeQuestionGenerator()
        consumer, _ = _build_consumer(generator)

        await consumer._handle_task(task_id="task-1", item_id="item-1")

        self.assertEqual([], generator.called_with)
        self.assertEqual([], self.evals().finalized)

    async def test_missing_item_marks_task_failed(self) -> None:
        FakeEvalRepository.item = None
        consumer, _ = _build_consumer(FakeQuestionGenerator())

        await consumer._handle_task(task_id="task-1", item_id="item-1")

        self.assertEqual(EvalTaskStatus.FAILED, FakeEvalTaskRepository.task.status)

    async def test_missing_chunk_point_fails_without_retry_and_finalizes(self) -> None:
        """点没了（文档被删或重建）：重试变不出原文来，直接终态。"""

        FakeVectorRepository.chunk = None
        generator = FakeQuestionGenerator()
        consumer, _ = _build_consumer(generator)

        await consumer._handle_task(task_id="task-1", item_id="item-1")

        self.assertEqual([], generator.called_with)
        self.assertEqual(EvalTaskStatus.FAILED, FakeEvalTaskRepository.task.status)
        self.assertEqual(EvalItemStatus.FAILED, FakeEvalRepository.item.status)
        self.assertIn("取不到可出题的原文", FakeEvalRepository.item.error_message)
        self.assertEqual(["ts-1"], self.evals().finalized)

    async def test_blank_chunk_text_fails_without_retry_and_finalizes(self) -> None:
        FakeVectorRepository.chunk = _chunk("   ")
        generator = FakeQuestionGenerator()
        consumer, _ = _build_consumer(generator)

        await consumer._handle_task(task_id="task-1", item_id="item-1")

        self.assertEqual([], generator.called_with)  # 出不了题，重试无意义
        self.assertEqual(EvalTaskStatus.FAILED, FakeEvalTaskRepository.task.status)
        self.assertEqual(EvalItemStatus.FAILED, FakeEvalRepository.item.status)
        self.assertEqual(["ts-1"], self.evals().finalized)

    async def test_llm_failure_below_max_back_to_pending_without_finalize(self) -> None:
        FakeEvalTaskRepository.task = _task(attempts=settings.eval_task_max_attempts - 2)
        consumer, _ = _build_consumer(FakeQuestionGenerator(error=RuntimeError("llm down")))

        await consumer._handle_task(task_id="task-1", item_id="item-1")

        task = FakeEvalTaskRepository.task
        item = FakeEvalRepository.item
        self.assertEqual(EvalTaskStatus.PENDING, task.status)  # 等 publisher 重投
        self.assertEqual(settings.eval_task_max_attempts - 1, task.attempts)
        self.assertEqual("RuntimeError: llm down", task.last_error)
        self.assertIsNone(item.error_message)  # item 未受影响
        self.assertEqual([], self.evals().finalized)  # 还有 pending 条目，不收尾

    async def test_llm_failure_at_max_marks_both_failed_and_finalizes(self) -> None:
        """回归：失败条目以前不推进进度，测试集会永远停在 generating。"""

        FakeEvalTaskRepository.task = _task(attempts=settings.eval_task_max_attempts - 1)
        consumer, _ = _build_consumer(FakeQuestionGenerator(error=RuntimeError("llm down")))

        await consumer._handle_task(task_id="task-1", item_id="item-1")

        self.assertEqual(EvalTaskStatus.FAILED, FakeEvalTaskRepository.task.status)
        self.assertEqual(EvalItemStatus.FAILED, FakeEvalRepository.item.status)
        self.assertEqual(["ts-1"], self.evals().finalized)


class EvalQuestionConsumerMessageTests(_RepoFixture):
    """_process_single_message：字段校验与 ACK 规则。"""

    async def test_missing_fields_acks_and_skips(self) -> None:
        consumer, queue = _build_consumer()

        await consumer._process_single_message("msg-1", {"item_id": "item-1"})  # 缺 task_id

        self.assertEqual(["msg-1"], queue.acked)

    async def test_success_commits_then_acks(self) -> None:
        consumer, queue = _build_consumer()

        await consumer._process_single_message(
            "msg-1", {"task_id": "task-1", "item_id": "item-1"}
        )

        self.assertEqual(["msg-1"], queue.acked)

    async def test_commit_failure_does_not_ack(self) -> None:
        session = FakeSession(commit_error=RuntimeError("db gone"))
        consumer, queue = _build_consumer(session=session)

        await consumer._process_single_message(
            "msg-1", {"task_id": "task-1", "item_id": "item-1"}
        )

        self.assertEqual([], queue.acked)  # 不 ACK，留 XAUTOCLAIM 恢复


if __name__ == "__main__":
    import unittest

    unittest.main()
