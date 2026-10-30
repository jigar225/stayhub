"""Booked-policy preview and atomic guest/host cancellation operations."""

import json
from collections.abc import Callable
from datetime import timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import jwt
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app import booking_ledger, booking_service, business_time
from app.auth_service import AccessContext, current_user
from app.booking_schemas import DeclineInput, ReservationResponse
from app.config import get_settings
from app.errors import ApiError
from app.financial_schemas import (
    CancelInput,
    CancellationClaims,
    CancellationPreview,
    CancellationQuoteResponse,
)
from app.models import CalendarEntry, Payment, Payout, Refund, Reservation
from app.refunds import RefundAmounts, calculate


def _owned(db: Session, actor: AccessContext, rid: UUID, role: str) -> Reservation:
    current_user(db, actor, role)
    row = db.get(Reservation, rid)
    if (
        row is None
        or (row.guest_id if role == "guest" else row.host_id) != actor.user_id
    ):
        raise ApiError(404, "not_found", "This reservation could not be found.")
    return row


def _locked(db: Session, row: Reservation) -> Reservation:
    booking_service._locked_listing(db, row.listing_id)
    result = db.scalar(
        select(Reservation)
        .where(Reservation.id == row.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert result is not None
    return result


def _amounts(row: Reservation, now: Any, full: bool = False) -> RefundAmounts:
    if row.state not in {"pending", "confirmed"}:
        raise ApiError(
            409, "invalid_state", "This reservation can no longer be cancelled."
        )
    if now >= row.scheduled_check_in:
        raise ApiError(
            409,
            "cancellation_unavailable",
            "Cancellation is only available before scheduled check-in.",
        )
    return calculate(
        cast(dict[str, Any], row.policy_snapshot["definition"]),
        row.created_at,
        row.scheduled_check_in,
        now,
        row.nights_minor,
        row.cleaning_minor,
        row.guest_fee_minor,
        full=full or row.state == "pending",
    )


def _expired(db: Session, row: Reservation, actor: AccessContext, now: Any) -> bool:
    if (
        row.state == "pending"
        and row.request_deadline is not None
        and now >= row.request_deadline
    ):
        booking_ledger.decline(db, row, actor.user_id, "expired", now, expired=True)
        return True
    return False


def preview(
    db: Session,
    actor: AccessContext,
    rid: UUID,
    guard: Callable[[], None] | None = None,
) -> CancellationQuoteResponse | booking_service.CommittedFailure:
    with db.begin():
        row = _owned(db, actor, rid, "guest")
        if guard:
            guard()
        row = _locked(db, row)
        now = business_time.at(db)
        if _expired(db, row, actor, now):
            result: CancellationQuoteResponse | booking_service.CommittedFailure = (
                booking_service.CommittedFailure(
                    "request_expired",
                    "This unanswered request expired and was fully refunded.",
                )
            )
        else:
            amounts = _amounts(row, now)
            settings = get_settings()
            expiry = now + timedelta(minutes=5)
            claims = {
                **amounts.values(),
                "actor_id": str(actor.user_id),
                "reservation_id": str(row.id),
                "state": row.state,
                "financial_version": row.financial_version,
                "iat": now,
                "exp": expiry,
                "iss": settings.jwt_issuer,
                "aud": "stayhub-cancellation",
                "purpose": "cancellation",
            }
            token = jwt.encode(
                claims, settings.jwt_secret.get_secret_value(), algorithm="HS256"
            )
            definition = cast(dict[str, Any], row.policy_snapshot["definition"])
            if row.state == "pending":
                cutoff = "Pending requests receive a full refund before check-in."
            elif definition.get(
                "booking_grace_hours"
            ) is not None and now - row.created_at <= timedelta(
                hours=definition["booking_grace_hours"]
            ):
                cutoff = f"Your booked policy refunds {amounts.refund_percent}% within {definition['booking_grace_hours']} elapsed hours of booking, strictly before check-in."
            else:
                windows = sorted(
                    definition["windows"],
                    key=lambda window: window["hours_before"],
                    reverse=True,
                )
                matched = next(
                    (
                        window
                        for window in windows
                        if row.scheduled_check_in - now
                        >= timedelta(hours=window["hours_before"])
                    ),
                    None,
                )
                hours = matched["hours_before"] if matched else 0
                cutoff = f"Your booked policy refunds {amounts.refund_percent}% at least {hours} elapsed hours before check-in (exact cutoff included)."
                if amounts.refund_percent == 0:
                    next_tier = min(
                        (
                            window["hours_before"]
                            for window in windows
                            if window["percent"] > 0
                        ),
                        default=0,
                    )
                    cutoff = f"Less than {next_tier} elapsed hours remain before check-in; booked nights and the original guest service fee receive a 0% refund."
            explanation = (
                cutoff
                + " The percentage applies separately to nights and the original guest service fee. Cleaning is refunded in full before check-in."
            )
            result = CancellationQuoteResponse(
                preview=CancellationPreview(
                    **amounts.values(),
                    reservation_id=row.id,
                    state=row.state,
                    financial_version=row.financial_version,
                    policy_name=str(row.policy_snapshot["name"]),
                    policy_version=int(cast(Any, row.policy_snapshot["version"])),
                    explanation=explanation,
                    expires_at=expiry,
                    confirmation_token=token,
                )
            )
    return result


def _decode(token: str) -> CancellationClaims:
    settings = get_settings()
    try:
        data = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            audience="stayhub-cancellation",
            options={
                "verify_exp": False,
                "verify_iat": False,
                "require": ["iat", "exp", "iss", "aud", "purpose"],
            },
        )
        return CancellationClaims.model_validate_json(json.dumps(data), strict=True)
    except (jwt.InvalidTokenError, ValidationError, ValueError, TypeError):
        raise ApiError(
            422,
            "invalid_cancellation_quote",
            "This cancellation preview is invalid. Request a fresh preview.",
        ) from None


def _apply(
    db: Session,
    row: Reservation,
    actor: AccessContext,
    amounts: RefundAmounts,
    reason: str,
    host: bool,
    now: Any,
) -> None:
    previous = row.state
    row.state = "cancelled_by_host" if host else "cancelled_by_guest"
    row.reason = reason
    row.cancelled_at = now
    row.financial_version += 1
    row.effective_host_fee_minor = amounts.effective_host_fee_minor
    row.host_entitlement_minor = amounts.host_entitlement_minor
    row.platform_entitlement_minor = amounts.platform_entitlement_minor
    entry = db.scalar(
        select(CalendarEntry).where(CalendarEntry.reservation_id == row.id)
    )
    assert entry is not None
    entry.active = False
    payment = db.scalar(select(Payment).where(Payment.reservation_id == row.id))
    payout = db.scalar(
        select(Payout).where(Payout.reservation_id == row.id).with_for_update()
    )
    assert payment is not None and payout is not None and payout.status != "paid"
    payout.gross_minor = amounts.retained_nights_minor
    payout.host_fee_minor = amounts.effective_host_fee_minor
    payout.net_minor = amounts.host_entitlement_minor
    payout.status = "scheduled" if payout.net_minor else "cancelled"
    refund = Refund(
        id=uuid4(),
        payment_id=payment.id,
        reservation_id=row.id,
        operation_id=f"terminal-refund:{row.id}",
        original_charge_minor=payment.amount_minor,
        amount_minor=amounts.total_refund_minor,
        nights_minor=amounts.nights_refund_minor,
        cleaning_minor=amounts.cleaning_refund_minor,
        guest_fee_minor=amounts.guest_fee_refund_minor,
        reason=reason,
        refunded_at=now,
    )
    db.add(refund)
    booking_ledger.event(
        db,
        actor.user_id,
        f"reservation.{row.state}",
        "reservation",
        row.id,
        {"state": previous},
        {
            "state": row.state,
            "reason": reason,
            "host_entitlement_minor": row.host_entitlement_minor,
            "platform_entitlement_minor": row.platform_entitlement_minor,
        },
        now,
    )
    booking_ledger.event(
        db,
        actor.user_id,
        "payment.refunded",
        "refund",
        refund.id,
        None,
        {
            "reservation_id": str(row.id),
            "payment_id": str(payment.id),
            "amount_minor": refund.amount_minor,
            "reason": reason,
        },
        now,
    )
    booking_ledger.event(
        db,
        actor.user_id,
        "payout.updated",
        "payout",
        payout.id,
        None,
        {
            "status": payout.status,
            "net_minor": payout.net_minor,
            "host_fee_minor": payout.host_fee_minor,
        },
        now,
    )
    db.flush()


def cancel(
    db: Session,
    actor: AccessContext,
    rid: UUID,
    body: CancelInput | DeclineInput,
    key: str,
    *,
    host: bool = False,
    guard: Callable[[], None] | None = None,
) -> ReservationResponse | booking_service.CommittedFailure:
    try:
        with db.begin():
            row = _owned(db, actor, rid, "host" if host else "guest")
            if guard:
                guard()
            key = booking_service._key(key)
            operation = f"{'host-cancel' if host else 'cancel'}:{rid}"
            fingerprint = booking_service._fingerprint(body.model_dump())
            replay = booking_service._replay(db, actor, operation, key, fingerprint)
            if replay:
                return replay
            row = _locked(db, row)
            now = business_time.at(db)
            if not host and _expired(db, row, actor, now):
                result: ReservationResponse | booking_service.CommittedFailure = (
                    booking_service.CommittedFailure(
                        "request_expired",
                        "This request expired and was fully refunded.",
                    )
                )
            else:
                if host and row.state != "confirmed":
                    raise ApiError(
                        409,
                        "invalid_state",
                        "Only confirmed stays can be host-cancelled. Decline pending requests instead.",
                    )
                amounts = _amounts(row, now, full=host)
                if not host:
                    assert isinstance(body, CancelInput)
                    claims = _decode(body.confirmation_token)
                    if claims.exp <= claims.iat or now.timestamp() < claims.iat:
                        raise ApiError(
                            422,
                            "invalid_cancellation_quote",
                            "Invalid preview timestamps.",
                        )
                    if now.timestamp() >= claims.exp:
                        raise ApiError(
                            409,
                            "cancellation_quote_expired",
                            "This preview expired. Review a fresh refund before confirming.",
                        )
                    expected = {
                        **amounts.values(),
                        "actor_id": actor.user_id,
                        "reservation_id": row.id,
                        "state": row.state,
                        "financial_version": row.financial_version,
                    }
                    if any(getattr(claims, k) != v for k, v in expected.items()):
                        raise ApiError(
                            409,
                            "stale_cancellation",
                            "The cancellation terms changed. Review a fresh refund before confirming.",
                        )
                reason = (
                    body.reason if isinstance(body, DeclineInput) else "guest_cancelled"
                )
                _apply(db, row, actor, amounts, reason, host, now)
                result = booking_ledger.output(db, row)
                booking_service._remember(
                    db, actor, operation, key, fingerprint, result, 200
                )
        return result
    except (IntegrityError, OperationalError) as error:
        booking_service._contention(error)
