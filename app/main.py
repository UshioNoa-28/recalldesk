"""FastAPI 应用入口。

运行：
    uvicorn app.main:app --reload

队列型后台任务拆在独立进程（六条腿：文档索引 / 出题 / 逐题评测 × publisher / consumer）：
    python -m app.publisher.document
    python -m app.consumer.document
    python -m app.publisher.eval
    python -m app.consumer.eval
    python -m app.publisher.eval_run
    python -m app.consumer.eval_run

评测 run 也在这套里：POST /eval/testsets/{id}/runs 只登记 run 与逐题任务，
检索由 eval_run consumer 跑 —— API 进程重启不再打断任何后台工作，
所以启动时没有「遗留 running 收尾」这回事了。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI

from app.api import router as api_router
from app.container import create_container
from app.infrastructure.postgres.db import run_migrations
from settings import settings


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    """启动：迁移。退出：关闭 DI 容器。

    后台工作全在队列里，崩溃恢复由 XAUTOCLAIM 认领负责，
    这里没有要收尾的进程内任务。
    """

    await run_migrations(settings.database_url)
    yield
    await container.close()


logging.getLogger("neo4j.notifications").setLevel(logging.WARNING)

container = create_container()


def create_app() -> FastAPI:
    app = FastAPI(title="RecallDesk", version="0.2.0", lifespan=lifespan)
    app.include_router(api_router)
    setup_dishka(container, app)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """存活检查，供 Docker healthcheck 使用。"""

        return {"status": "ok"}

    return app


app = create_app()


__all__ = ["app", "create_app"]
