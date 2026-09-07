"""PostgreSQL 引擎/会话工厂与迁移助手。"""

from __future__ import annotations

import asyncio

from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from settings import settings


def build_engine() -> AsyncEngine:
    """创建应用级异步引擎。"""

    return create_async_engine(settings.database_url, pool_pre_ping=True)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """从引擎创建 Session 工厂。"""

    return async_sessionmaker(engine, expire_on_commit=False)


async def run_migrations() -> None:
    """应用启动时把 schema 升级到最新（alembic upgrade head）。"""

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", settings.database_url)
    await asyncio.to_thread(command.upgrade, config, "head")


__all__ = ["build_engine", "build_session_factory", "run_migrations"]
