"""事务边界的 SQLAlchemy 实现。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.ports.unit_of_work import UnitOfWork


class SqlAlchemyUnitOfWork(UnitOfWork):
    """把 AsyncSession 的事务控制暴露为 UnitOfWork 端口。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()


__all__ = ["SqlAlchemyUnitOfWork"]
