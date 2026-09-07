"""全表共用：DeclarativeBase 与时间默认值。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import DeclarativeBase


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


__all__ = ["Base", "utc_now"]
