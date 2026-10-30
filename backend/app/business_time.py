"""Persisted business clock; security clocks deliberately remain real UTC.

`at(db)` is transaction-scoped and never begins a nested transaction. Existing
injected `now` seams continue to work in fixed-time regressions.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import AppClock


def real_now() -> datetime:
    return datetime.now(UTC)


def now() -> datetime:
    with get_engine().connect() as connection:
        offset = connection.scalar(
            select(AppClock.offset_seconds).where(AppClock.id == 1)
        )
    if offset is None:
        raise RuntimeError("Business clock singleton is missing; run migrations.")
    return real_now() + timedelta(seconds=offset)


_default_now = now


def at(db: Session) -> datetime:
    if now is not _default_now:
        return now()
    offset = db.scalar(select(AppClock.offset_seconds).where(AppClock.id == 1))
    if offset is None:
        raise RuntimeError("Business clock singleton is missing; run migrations.")
    return real_now() + timedelta(seconds=offset)
