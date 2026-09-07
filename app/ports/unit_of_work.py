"""事务边界端口。"""

from __future__ import annotations

from typing import Protocol


class UnitOfWork(Protocol):
    """一次业务用例的事务边界。"""

    async def commit(self) -> None:
        """提交当前事务。"""
        ...

    async def rollback(self) -> None:
        """回滚当前事务。"""
        ...


__all__ = ["UnitOfWork"]
