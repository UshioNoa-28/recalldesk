"""FastAPI 应用入口。

运行：
    uvicorn app.main:app --reload

队列型后台任务拆在独立进程：
    python -m app.publisher.document
    python -m app.consumer.document
    python -m app.publisher.eval
    python -m app.consumer.eval

只有评测运行（eval run）在本进程后台跑：它不碰队列，跑完就是几百次检索，
拆出去得连 PG 与 Qdrant 配置一起搬，所以留在 API 进程里 —— 代价是重启会打断它，
于是 lifespan 启动时要给它收尾。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api import router as api_router
from app.application.services.eval_run_executor import fail_stale_runs
from app.container import create_container
from app.infrastructure.db import run_migrations


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    """启动：迁移 + 给上次进程遗留的评测运行收尾。退出：关闭 DI 容器。

    run 是进程内任务，进程一死它就停了，但 DB 里的行还写着 running：
    迁移之后、开始接活之前扫一次，把那些行标成 failed。
    """

    await run_migrations()
    await fail_stale_runs(await container.get(async_sessionmaker[AsyncSession]))
    yield
    await container.close()


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
