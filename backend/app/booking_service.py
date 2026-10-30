"""Complete atomic Pay and host decisions; callers supply an idle Session."""

import hashlib
import json
import secrets
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
from typing import NoReturn
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app import booking_ledger, booking_quotes, business_time
from app.auth_service import AccessContext, current_user
from app.booking_schemas import DeclineInput, PayInput, ReservationResponse
from app.errors import ApiError
from app.models import (
    CalendarEntry,
    CancellationPolicy,
    IdempotencyRecord,
    Listing,
    Payment,
    Payout,
    Reservation,
    User,
)


@dataclass(frozen=True)
class CommittedFailure:
    code: str
    message: str


def _key(value: str) -> str:
    if (
        not 1 <= len(value) <= 128
        or not value.isascii()
        or any(ord(c) < 33 or ord(c) > 126 for c in value)
    ):
        raise ApiError(
            422,
            "validation_error",
            "Supply an Idempotency-Key (1–128 visible ASCII characters).",
            field_errors={
                "idempotency_key": "Use the original key when retrying this operation."
            },
        )
    return value


def _fingerprint(data: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _replay(
    db: Session,
    actor: AccessContext,
    operation: str,
    key: str,
    fingerprint: str,
) -> ReservationResponse | None:
    scope = f"{actor.user_id}:{operation}:{key}"
    lock = int.from_bytes(
        hashlib.sha256(scope.encode()).digest()[:8], "big", signed=True
    )
    if not db.scalar(
        select(text("pg_try_advisory_xact_lock(:lock)")).params(lock=lock)
    ):
        raise ApiError(
            409,
            "operation_in_progress",
            "This submission is still processing. Retry with the same key and payload.",
        )
    record = db.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.actor_id == actor.user_id,
            IdempotencyRecord.operation == operation,
            IdempotencyRecord.key == key,
        )
    )
    if record is None:
        return None
    if record.fingerprint != fingerprint:
        raise ApiError(
            409,
            "idempotency_conflict",
            "This key was already used for different input. Resolve the original submission first.",
        )
    result = ReservationResponse.model_validate(record.response_body)
    result._replay_body = record.response_body
    result._replay_status = record.status_code
    return result


def _remember(
    db: Session,
    actor: AccessContext,
    operation: str,
    key: str,
    fingerprint: str,
    result: ReservationResponse,
    status: int,
) -> None:
    db.add(
        IdempotencyRecord(
            actor_id=actor.user_id,
            operation=operation,
            key=key,
            fingerprint=fingerprint,
            status_code=status,
            response_body=result.model_dump(mode="json"),
        )
    )
    db.flush()


def _locked_listing(db: Session, listing_id: UUID) -> Listing:
    db.execute(text("SET LOCAL lock_timeout = '5s'"))
    listing = db.scalar(
        select(Listing)
        .where(Listing.id == listing_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if listing is None:
        raise ApiError(
            409, "stale_quote", "This stay no longer exists. Choose another stay."
        )
    return listing


def _contention(error: OperationalError | IntegrityError) -> NoReturn:
    state = getattr(error.orig, "sqlstate", None)
    if state == "23P01":
        raise ApiError(
            409,
            "availability_conflict",
            "These nights were just occupied. Choose other dates.",
        ) from None
    if state in {"40P01", "40001", "55P03"}:
        raise ApiError(
            409,
            "operation_in_progress",
            "Another operation is processing. Retry this exact submission with the same key.",
        ) from None
    raise error


def pay(
    db: Session,
    actor: AccessContext,
    body: PayInput,
    key: str,
    guard: Callable[[], None] | None = None,
) -> ReservationResponse:
    try:
        with db.begin():
            user = current_user(db, actor, "guest")
            if any(member.role == "admin" for member in user.memberships):
                raise ApiError(403, "forbidden", "Admin accounts cannot book stays.")
            if guard:
                guard()
            key = _key(key)
            fingerprint = _fingerprint(body.model_dump())
            replay = _replay(db, actor, "pay", key, fingerprint)
            if replay:
                return replay
            claims = booking_quotes.decode_quote(body.quote_token)
            listing = _locked_listing(db, claims.listing_id)
            if listing.owner_id == actor.user_id:
                raise ApiError(403, "own_listing", "You cannot book your own listing.")
            now = business_time.at(db)
            arrival, departure = booking_quotes.revalidate(db, listing, claims, now)
            host = db.get(User, listing.owner_id)
            policy = db.get(CancellationPolicy, listing.policy_id)
            assert (
                host is not None and policy is not None and listing.timezone is not None
            )
            fee = (claims.subtotal_minor * 3 + 50) // 100
            row = Reservation(
                id=uuid4(),
                code="SH-" + secrets.token_hex(8).upper(),
                listing_id=listing.id,
                guest_id=actor.user_id,
                host_id=listing.owner_id,
                state="pending" if listing.booking_mode == "request" else "confirmed",
                reason=None,
                booking_mode=listing.booking_mode,
                check_in=claims.check_in,
                check_out=claims.check_out,
                guests=claims.guests,
                timezone=listing.timezone,
                scheduled_check_in=arrival,
                scheduled_check_out=departure,
                created_at=now,
                request_deadline=now + timedelta(hours=24)
                if listing.booking_mode == "request"
                else None,
                listing_snapshot={
                    "title": listing.title,
                    "destination": listing.destination,
                    "property_type": listing.property_type,
                    "description": listing.description,
                    "amenities": deepcopy(listing.amenities or []),
                    "house_rules": deepcopy(listing.house_rules or []),
                    "host_name": host.name,
                },
                policy_snapshot={
                    **claims.policy.model_dump(mode="json"),
                    "definition": deepcopy(policy.definition),
                },
                nightly_minor=claims.nightly_minor,
                nights_minor=claims.nights_minor,
                cleaning_minor=claims.cleaning_minor,
                subtotal_minor=claims.subtotal_minor,
                guest_fee_minor=claims.guest_fee_minor,
                total_minor=claims.total_minor,
                host_fee_minor=fee,
                effective_host_fee_minor=fee,
                financial_version=1,
                host_entitlement_minor=claims.subtotal_minor - fee,
                platform_entitlement_minor=claims.guest_fee_minor + fee,
            )
            db.add(row)
            db.flush()
            db.add(
                Payout(
                    reservation_id=row.id,
                    host_id=row.host_id,
                    due_at=arrival + timedelta(hours=24),
                    gross_minor=row.subtotal_minor,
                    host_fee_minor=fee,
                    net_minor=row.host_entitlement_minor,
                    status="held" if row.state == "pending" else "scheduled",
                )
            )
            payment = Payment(
                id=uuid4(),
                reservation_id=row.id,
                operation_id=f"charge:{row.id}",
                amount_minor=row.total_minor,
                currency="EUR",
                paid_at=now,
            )
            db.add(payment)
            db.add(
                CalendarEntry(
                    listing_id=row.listing_id,
                    kind="reservation",
                    reservation_id=row.id,
                    check_in=row.check_in,
                    check_out=row.check_out,
                    active=True,
                )
            )
            booking_ledger.event(
                db,
                actor.user_id,
                "reservation.created",
                "reservation",
                row.id,
                None,
                {
                    "state": row.state,
                    "code": row.code,
                    "listing_id": str(row.listing_id),
                },
                now,
            )
            booking_ledger.event(
                db,
                actor.user_id,
                "payment.charged",
                "payment",
                payment.id,
                None,
                {
                    "reservation_id": str(row.id),
                    "amount_minor": payment.amount_minor,
                    "currency": "EUR",
                },
                now,
            )
            db.flush()
            result = booking_ledger.output(db, row)
            _remember(db, actor, "pay", key, fingerprint, result, 201)
        return result
    except (IntegrityError, OperationalError) as error:
        _contention(error)


def host_decision(
    db: Session,
    actor: AccessContext,
    reservation_id: UUID,
    decision: str,
    body: DeclineInput | None,
    key: str,
    guard: Callable[[], None] | None = None,
) -> ReservationResponse | CommittedFailure:
    try:
        with db.begin():
            current_user(db, actor, "host")
            candidate = db.scalar(
                select(Reservation).where(
                    Reservation.id == reservation_id,
                    Reservation.host_id == actor.user_id,
                )
            )
            if candidate is None:
                raise ApiError(404, "not_found", "This reservation could not be found.")
            if guard:
                guard()
            key = _key(key)
            operation = f"{decision}:{reservation_id}"
            fingerprint = _fingerprint(body.model_dump() if body else {})
            replay = _replay(db, actor, operation, key, fingerprint)
            if replay:
                return replay
            listing = _locked_listing(db, candidate.listing_id)
            if listing.owner_id != actor.user_id:
                raise ApiError(404, "not_found", "This reservation could not be found.")
            row = db.scalar(
                select(Reservation)
                .where(Reservation.id == reservation_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            assert row is not None
            now = business_time.at(db)
            if row.state != "pending":
                raise ApiError(
                    409,
                    "invalid_state",
                    "This request has already been decided. Refresh the reservation.",
                )
            assert row.request_deadline is not None
            if now >= row.request_deadline:
                booking_ledger.decline(
                    db, row, actor.user_id, "expired", now, expired=True
                )
                result: ReservationResponse | CommittedFailure = CommittedFailure(
                    "request_expired",
                    "This request expired and was fully refunded. The dates are available again.",
                )
            else:
                if decision == "accept":
                    row.state = "confirmed"
                    row.financial_version += 1
                    payout = db.scalar(
                        select(Payout)
                        .where(Payout.reservation_id == row.id)
                        .with_for_update()
                    )
                    assert payout is not None
                    payout.status = "scheduled"
                    booking_ledger.event(
                        db,
                        actor.user_id,
                        "reservation.accepted",
                        "reservation",
                        row.id,
                        {"state": "pending"},
                        {"state": "confirmed"},
                        now,
                    )
                    db.flush()
                else:
                    assert body is not None
                    booking_ledger.decline(db, row, actor.user_id, body.reason, now)
                result = booking_ledger.output(db, row)
                _remember(db, actor, operation, key, fingerprint, result, 200)
        # CommittedFailure is deliberately translated by the adapter AFTER commit.
        return result
    except (IntegrityError, OperationalError) as error:
        _contention(error)
