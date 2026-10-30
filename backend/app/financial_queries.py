"""Authorized earnings aggregates and read-only audit projections."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import booking_ledger
from app.auth_service import AccessContext, current_user
from app.financial_schemas import (
    EarningsResponse,
    EventOutput,
    EventsResponse,
    PayoutsResponse,
)
from app.models import EventLog, Payout, Reservation


def payouts(
    db: Session,
    actor: AccessContext,
    status: str | None = None,
    limit: int = 20,
    cursor: UUID | None = None,
    *,
    earnings: bool = False,
) -> PayoutsResponse:
    with db.begin():
        current_user(db, actor, "host")
        criteria = [Payout.host_id == actor.user_id]
        if status:
            criteria.append(Payout.status == status)
        query = select(Payout).where(*criteria).order_by(Payout.id).limit(limit + 1)
        if cursor:
            query = query.where(Payout.id > cursor)
        rows = list(db.scalars(query))
        items = []
        for payout in rows[:limit]:
            row = db.get(Reservation, payout.reservation_id)
            assert row is not None
            value = booking_ledger.payout_output(db, row)
            assert value is not None
            items.append(value)
        next_cursor = str(rows[limit - 1].id) if len(rows) > limit else None
        if earnings:
            totals = {
                f"{label}_minor": int(
                    db.scalar(
                        select(func.coalesce(func.sum(Payout.net_minor), 0)).where(
                            Payout.host_id == actor.user_id,
                            Payout.status == state,
                            Payout.net_minor > 0,
                        )
                    )
                    or 0
                )
                for label, state in [
                    ("paid", "paid"),
                    ("upcoming", "scheduled"),
                    ("held", "held"),
                ]
            }
            result: PayoutsResponse = EarningsResponse(
                items=items, next_cursor=next_cursor, totals=totals
            )
        else:
            result = PayoutsResponse(items=items, next_cursor=next_cursor)
    return result


def events(
    db: Session,
    actor: AccessContext,
    action: str | None = None,
    target_id: UUID | None = None,
    limit: int = 20,
    cursor: UUID | None = None,
) -> EventsResponse:
    with db.begin():
        current_user(db, actor, "admin")
        query = select(EventLog).order_by(EventLog.id).limit(limit + 1)
        if action:
            query = query.where(EventLog.action == action)
        if target_id:
            query = query.where(EventLog.target_id == target_id)
        if cursor:
            query = query.where(EventLog.id > cursor)
        rows = list(db.scalars(query))
        result = EventsResponse(
            items=[EventOutput.model_validate(row) for row in rows[:limit]],
            next_cursor=str(rows[limit - 1].id) if len(rows) > limit else None,
        )
    return result
