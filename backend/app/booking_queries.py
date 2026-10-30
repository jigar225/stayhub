"""Party-authorized reservation reads; GET never changes business state."""

from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Date, func, or_, select
from sqlalchemy.orm import Session

from app import booking_ledger, business_time, discovery_service
from app.auth_service import AccessContext, current_user
from app.booking_schemas import (
    HostTodayOutput,
    ReservationResponse,
    ReservationsResponse,
)
from app.discovery_schemas import PublicPhotos
from app.errors import ApiError
from app.models import Listing, Reservation


def _party(db: Session, actor: AccessContext, reservation_id: UUID) -> Reservation:
    user = current_user(db, actor)
    roles = {membership.role for membership in user.memberships}
    row = db.get(Reservation, reservation_id)
    if row is None or not (
        (row.guest_id == user.id and "guest" in roles)
        or (row.host_id == user.id and "host" in roles)
    ):
        raise ApiError(404, "not_found", "This reservation could not be found.")
    return row


def detail(
    db: Session, actor: AccessContext, reservation_id: UUID
) -> ReservationResponse:
    with db.begin():
        result = booking_ledger.output(db, _party(db, actor, reservation_id))
    return result


def photos(db: Session, actor: AccessContext, reservation_id: UUID) -> PublicPhotos:
    with db.begin():
        row = _party(db, actor, reservation_id)
        listing = db.get(Listing, row.listing_id)
        assert listing is not None
        result = PublicPhotos(items=discovery_service._photos(listing))
    return result


def _page(
    db: Session, criteria: list[Any], limit: int, cursor: UUID | None
) -> ReservationsResponse:
    query = (
        select(Reservation).where(*criteria).order_by(Reservation.id).limit(limit + 1)
    )
    if cursor:
        query = query.where(Reservation.id > cursor)
    rows = list(db.scalars(query))
    return ReservationsResponse(
        items=[booking_ledger.output(db, row).reservation for row in rows[:limit]],
        next_cursor=str(rows[limit - 1].id) if len(rows) > limit else None,
    )


def guest_list(
    db: Session,
    actor: AccessContext,
    category: str = "all",
    limit: int = 20,
    cursor: UUID | None = None,
) -> ReservationsResponse:
    with db.begin():
        current_user(db, actor, "guest")
        criteria: list[Any] = [Reservation.guest_id == actor.user_id]
        now = business_time.at(db)
        if category == "pending":
            criteria.append(Reservation.state == "pending")
        elif category == "upcoming":
            criteria.extend(
                [
                    Reservation.state.in_(["pending", "confirmed", "checked_in"]),
                    Reservation.scheduled_check_out > now,
                ]
            )
        elif category == "past":
            criteria.extend(
                [
                    Reservation.state.in_(["confirmed", "completed"]),
                    Reservation.scheduled_check_out <= now,
                ]
            )
        elif category == "cancelled":
            criteria.append(
                Reservation.state.in_(
                    ["declined", "cancelled_by_guest", "cancelled_by_host"]
                )
            )
        result = _page(db, criteria, limit, cursor)
    return result


def host_list(
    db: Session,
    actor: AccessContext,
    state: str | None = None,
    limit: int = 20,
    cursor: UUID | None = None,
) -> ReservationsResponse:
    with db.begin():
        current_user(db, actor, "host")
        criteria: list[Any] = [Reservation.host_id == actor.user_id]
        if state:
            criteria.append(Reservation.state == state)
        result = _page(db, criteria, limit, cursor)
    return result


def today(
    db: Session, actor: AccessContext, limit: int = 20, cursor: UUID | None = None
) -> HostTodayOutput:
    with db.begin():
        now = business_time.at(db)
        current_user(db, actor, "host")
        page = _page(
            db,
            [
                Reservation.host_id == actor.user_id,
                or_(
                    Reservation.state == "pending",
                    (Reservation.state == "confirmed")
                    & (Reservation.scheduled_check_in > now),
                    Reservation.state == "checked_in",
                    (Reservation.state == "completed")
                    & (
                        func.timezone(
                            Reservation.timezone, Reservation.scheduled_check_out
                        ).cast(Date)
                        == func.timezone(Reservation.timezone, now).cast(Date)
                    ),
                ),
            ],
            limit,
            cursor,
        )
        result = HostTodayOutput(
            pending=[row for row in page.items if row.state == "pending"],
            upcoming=[
                row
                for row in page.items
                if row.state == "confirmed" and row.scheduled_check_in > now
            ],
            hosting=[row for row in page.items if row.state == "checked_in"],
            checkouts=[
                row
                for row in page.items
                if row.state == "completed"
                and row.scheduled_check_out.astimezone(ZoneInfo(row.timezone)).date()
                == now.astimezone(ZoneInfo(row.timezone)).date()
            ],
            next_cursor=page.next_cursor,
        )
    return result
