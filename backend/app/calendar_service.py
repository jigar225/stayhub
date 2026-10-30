"""Owner calendar workflows. PostgreSQL exclusion is the occupancy authority."""

from collections.abc import Callable
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth_service import AccessContext, current_user
from app.date_rules import invalid_date, read_range, stay_range
from app.discovery_schemas import (
    BlockOutput,
    BlockResponse,
    CalendarResponse,
    ReservationOccupancy,
    StayDates,
)
from app.errors import ApiError
from app.listing_service import _owned_listing
from app.models import CalendarEntry, Listing, Reservation


def listing_timezone(listing: Listing) -> str:
    if not listing.timezone:
        raise invalid_date(
            "Save the listing timezone before using its calendar.", "timezone"
        )
    return listing.timezone


def calendar(
    db: Session, actor: AccessContext, listing_id: UUID, start: date, end: date
) -> CalendarResponse:
    with db.begin():
        listing = _owned_listing(db, current_user(db, actor, "host"), listing_id)
        timezone = listing_timezone(listing)
        read_range(start, end, timezone)
        entries = db.scalars(
            select(CalendarEntry)
            .where(
                CalendarEntry.listing_id == listing_id,
                CalendarEntry.active,
                CalendarEntry.check_in < end,
                CalendarEntry.check_out > start,
            )
            .order_by(CalendarEntry.check_in, CalendarEntry.id)
        )
        result = CalendarResponse(
            listing_id=listing_id,
            timezone=timezone,
            start=start,
            end=end,
            items=[_occupancy(db, item) for item in entries],
        )
    return result


def create_block(
    db: Session,
    actor: AccessContext,
    listing_id: UUID,
    body: StayDates,
    guard: Callable[[], None] | None = None,
) -> BlockResponse:
    try:
        with db.begin():
            listing = _owned_listing(
                db, current_user(db, actor, "host"), listing_id, lock=True
            )
            if guard:
                guard()
            stay_range(body.check_in, body.check_out, listing_timezone(listing))
            block = CalendarEntry(
                listing_id=listing_id,
                kind="block",
                check_in=body.check_in,
                check_out=body.check_out,
            )
            db.add(block)
            db.flush()
            result = BlockResponse(block=BlockOutput.model_validate(block))
        return result
    except IntegrityError as error:
        if getattr(error.orig, "sqlstate", None) == "23P01":
            raise ApiError(
                409,
                "availability_conflict",
                "These dates overlap an existing block or occupied stay.",
            ) from None
        raise


def remove_block(
    db: Session,
    actor: AccessContext,
    listing_id: UUID,
    block_id: UUID,
    guard: Callable[[], None] | None = None,
) -> None:
    with db.begin():
        _owned_listing(db, current_user(db, actor, "host"), listing_id, lock=True)
        if guard:
            guard()
        block = db.scalar(
            select(CalendarEntry)
            .where(
                CalendarEntry.id == block_id,
                CalendarEntry.listing_id == listing_id,
                CalendarEntry.kind == "block",
            )
            .with_for_update()
        )
        if block is None:
            raise ApiError(404, "not_found", "This calendar block could not be found.")
        block.active = False


def _occupancy(db: Session, item: CalendarEntry) -> BlockOutput | ReservationOccupancy:
    if item.kind == "block":
        return BlockOutput.model_validate(item)
    assert item.reservation_id is not None
    row = db.get(Reservation, item.reservation_id)
    assert row is not None and row.state in {
        "pending",
        "confirmed",
        "checked_in",
        "completed",
    }
    return ReservationOccupancy.model_validate(
        {
            "id": item.id,
            "kind": "reservation",
            "check_in": item.check_in,
            "check_out": item.check_out,
            "reservation_id": row.id,
            "state": row.state,
            "code": row.code,
        }
    )
