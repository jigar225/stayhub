"""Transaction-scoped immutable projections, audit and terminal refund helpers."""

from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.booking_schemas import (
    ListingSnapshot,
    PaymentOutput,
    PolicySnapshot,
    RefundOutput,
    ReservationOutput,
    ReservationResponse,
)
from app.discovery_schemas import PriceBreakdown
from app.financial_schemas import PayoutOutput
from app.models import CalendarEntry, EventLog, Payment, Payout, Refund, Reservation


def output(db: Session, row: Reservation) -> ReservationResponse:
    payment = db.scalar(select(Payment).where(Payment.reservation_id == row.id))
    assert payment is not None
    refund = db.scalar(select(Refund).where(Refund.reservation_id == row.id))
    return ReservationResponse(
        reservation=ReservationOutput(
            id=row.id,
            code=row.code,
            listing_id=row.listing_id,
            guest_id=row.guest_id,
            host_id=row.host_id,
            state=cast(Any, row.state),
            reason=row.reason,
            booking_mode=cast(Literal["instant", "request"], row.booking_mode),
            check_in=row.check_in,
            check_out=row.check_out,
            guests=row.guests,
            timezone=row.timezone,
            scheduled_check_in=row.scheduled_check_in,
            scheduled_check_out=row.scheduled_check_out,
            created_at=row.created_at,
            request_deadline=row.request_deadline,
            listing_snapshot=ListingSnapshot.model_validate(row.listing_snapshot),
            policy=PolicySnapshot.model_validate(row.policy_snapshot),
            price=PriceBreakdown(
                nights=(row.check_out - row.check_in).days,
                nightly_minor=row.nightly_minor,
                nights_minor=row.nights_minor,
                cleaning_minor=row.cleaning_minor,
                subtotal_minor=row.subtotal_minor,
                guest_fee_minor=row.guest_fee_minor,
                total_minor=row.total_minor,
            ),
            host_fee_minor=row.host_fee_minor,
            host_entitlement_minor=row.host_entitlement_minor,
            platform_entitlement_minor=row.platform_entitlement_minor,
            payment=PaymentOutput.model_validate(payment),
            refund=RefundOutput.model_validate(refund) if refund else None,
            financial_version=row.financial_version,
            effective_host_fee_minor=row.effective_host_fee_minor,
            cancelled_at=row.cancelled_at,
            payout=payout_output(db, row),
        )
    )


def event(
    db: Session,
    actor_id: UUID | None,
    action: str,
    target_type: str,
    target_id: UUID,
    before: dict[str, object] | None,
    after: dict[str, object],
    now: datetime,
    *,
    system_identity: str = "request-expiry",
) -> None:
    db.add(
        EventLog(
            actor_id=actor_id,
            system_identity=system_identity if actor_id is None else None,
            action=action,
            target_type=target_type,
            target_id=target_id,
            before=before,
            after=after,
            business_at=now,
        )
    )


def decline(
    db: Session,
    row: Reservation,
    actor_id: UUID | None,
    reason: str,
    now: datetime,
    *,
    expired: bool = False,
) -> None:
    # Caller holds listing then reservation lock and has checked pending state.
    payout = db.scalar(
        select(Payout).where(Payout.reservation_id == row.id).with_for_update()
    )
    row.financial_version += 1
    row.effective_host_fee_minor = 0
    row.state = "declined"
    row.reason = reason
    row.host_entitlement_minor = 0
    row.platform_entitlement_minor = 0
    if payout is not None:
        payout.status = "cancelled"
        payout.gross_minor = payout.host_fee_minor = payout.net_minor = 0
    entry = db.scalar(
        select(CalendarEntry).where(CalendarEntry.reservation_id == row.id)
    )
    assert entry is not None
    entry.active = False
    payment = db.scalar(select(Payment).where(Payment.reservation_id == row.id))
    assert payment is not None
    refund = Refund(
        id=uuid4(),
        payment_id=payment.id,
        reservation_id=row.id,
        operation_id=f"full-refund:{row.id}",
        amount_minor=payment.amount_minor,
        original_charge_minor=payment.amount_minor,
        nights_minor=row.nights_minor,
        cleaning_minor=row.cleaning_minor,
        guest_fee_minor=row.guest_fee_minor,
        reason=reason,
        refunded_at=now,
    )
    db.add(refund)
    event(
        db,
        actor_id,
        "reservation.expired" if expired else "reservation.declined",
        "reservation",
        row.id,
        {"state": "pending"},
        {
            "state": "declined",
            "reason": reason,
            "host_entitlement_minor": 0,
            "platform_entitlement_minor": 0,
        },
        now,
    )
    event(
        db,
        actor_id,
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
    db.flush()


def payout_output(db: Session, row: Reservation) -> PayoutOutput | None:
    payout = db.scalar(select(Payout).where(Payout.reservation_id == row.id))
    if payout is None:
        return None
    return PayoutOutput(
        id=payout.id,
        reservation_id=row.id,
        code=row.code,
        listing_title=str(row.listing_snapshot["title"]),
        host_id=payout.host_id,
        due_at=payout.due_at,
        gross_minor=payout.gross_minor,
        host_fee_minor=payout.host_fee_minor,
        net_minor=payout.net_minor,
        status=cast(Any, payout.status),
        paid_at=payout.paid_at,
        retained_cancellation=row.state in {"cancelled_by_guest", "cancelled_by_host"}
        and payout.net_minor > 0,
    )
