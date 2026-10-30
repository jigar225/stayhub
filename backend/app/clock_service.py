"""Global forward-only demo advancement, separate from bounded sweep transactions."""

import hashlib
from collections.abc import Callable
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app import booking_ledger, booking_service, business_time, sweep
from app.auth_service import AccessContext, current_user
from app.config import get_settings
from app.errors import ApiError
from app.financial_schemas import (
    AdvanceInput,
    AdvanceResponse,
    BusinessTimeResponse,
    ClockOutput,
    SweepResult,
)
from app.models import AppClock, IdempotencyRecord


def _clock(db: Session) -> ClockOutput:
    row = db.get(AppClock, 1)
    assert row is not None
    real = business_time.real_now()
    return ClockOutput(
        business_now=real + timedelta(seconds=row.offset_seconds),
        real_now=real,
        offset_seconds=row.offset_seconds,
        version=row.version,
        demo_mode=get_settings().demo_mode,
    )


def public_time(db: Session) -> BusinessTimeResponse:
    with db.begin():
        value = _clock(db)
    return BusinessTimeResponse(
        business_now=value.business_now, real_now=value.real_now
    )


def clock(db: Session, actor: AccessContext) -> ClockOutput:
    with db.begin():
        current_user(db, actor, "admin")
        result = _clock(db)
    return result


def _advance(
    db: Session,
    actor: AccessContext,
    body: AdvanceInput,
    key: str,
    guard: Callable[[], None] | None = None,
) -> AdvanceResponse:
    with db.begin():
        current_user(db, actor, "admin")
        if guard:
            guard()
        if not get_settings().demo_mode:
            raise ApiError(
                403,
                "demo_disabled",
                "Demo clock advancement is disabled in this environment.",
            )
        key = booking_service._key(key)
        fingerprint = booking_service._fingerprint(body.model_dump())
        operation = "clock-advance"
        lock = int.from_bytes(
            hashlib.sha256(f"{actor.user_id}:{operation}:{key}".encode()).digest()[:8],
            "big",
            signed=True,
        )
        if not db.scalar(
            select(text("pg_try_advisory_xact_lock(:lock)")).params(lock=lock)
        ):
            raise ApiError(
                409,
                "operation_in_progress",
                "Advance is processing. Retry the same key and delta.",
            )
        stored = db.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.actor_id == actor.user_id,
                IdempotencyRecord.operation == operation,
                IdempotencyRecord.key == key,
            )
        )
        if stored:
            if stored.fingerprint != fingerprint:
                raise ApiError(
                    409,
                    "idempotency_conflict",
                    "This key was used for a different advance.",
                )
            result = AdvanceResponse.model_validate(stored.response_body)
        else:
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            row = db.scalar(
                select(AppClock)
                .where(AppClock.id == 1)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            assert row is not None
            previous = row.offset_seconds
            row.offset_seconds += body.seconds
            row.version += 1
            db.flush()
            snapshot = _clock(db)
            booking_ledger.event(
                db,
                actor.user_id,
                "clock.advanced",
                "app_clock",
                uuid4(),
                {"offset_seconds": previous},
                {"offset_seconds": row.offset_seconds, "version": row.version},
                snapshot.business_now,
            )
            result = AdvanceResponse(clock=snapshot, sweep=SweepResult())
            db.add(
                IdempotencyRecord(
                    actor_id=actor.user_id,
                    operation=operation,
                    key=key,
                    fingerprint=fingerprint,
                    status_code=200,
                    response_body=result.model_dump(mode="json"),
                )
            )
            db.flush()
    # Advancement is committed even if sweep is interrupted; replay keeps the
    # original clock snapshot while safely resuming outstanding due work.
    try:
        result.sweep = sweep.run(db)
    except Exception:
        result.sweep = SweepResult(deferred=1, has_more=True)
    return result


def admin_sweep(
    db: Session,
    actor: AccessContext,
    batch_size: int,
    guard: Callable[[], None] | None = None,
) -> SweepResult:
    with db.begin():
        current_user(db, actor, "admin")
        if guard:
            guard()
    return sweep.run(db, batch_size)


def advance(
    db: Session,
    actor: AccessContext,
    body: AdvanceInput,
    key: str,
    guard: Callable[[], None] | None = None,
) -> AdvanceResponse:
    try:
        return _advance(db, actor, body, key, guard)
    except OperationalError as error:
        booking_service._contention(error)
