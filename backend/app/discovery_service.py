"""Published-only public reads with explicit allowlisted projections."""

from datetime import date, timedelta
from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import Date, func, select
from sqlalchemy import cast as sql_cast
from sqlalchemy.orm import Session

from app import business_time, pricing, storage
from app.date_rules import invalid_date, read_range, stay_range
from app.discovery_schemas import (
    AvailabilityResponse,
    PublicDetail,
    PublicListingResponse,
    PublicListings,
    PublicPhoto,
    PublicPhotos,
    PublicSummary,
    QuoteInput,
    QuoteResponse,
    StayDates,
)
from app.errors import ApiError
from app.models import CalendarEntry, DemoImport, Listing, User

DEMO_LABEL = "Fictional demo stay · illustrative licensed photos"


def _published(db: Session, listing_id: UUID) -> Listing:
    listing = db.scalar(
        select(Listing)
        .where(Listing.id == listing_id, Listing.status == "published")
        .execution_options(populate_existing=True)
    )
    if listing is None:
        raise ApiError(404, "not_found", "This stay could not be found.")
    return listing


def _photos(listing: Listing, cover_only: bool = False) -> list[PublicPhoto]:
    verified = sorted(
        (
            photo
            for photo in listing.photos
            if photo.state == "verified" and photo.final_key
        ),
        key=lambda photo: (photo.order or 0, str(photo.id)),
    )
    if cover_only:
        verified = verified[:1]
    # Presigned storage authorizations use real time, even when future business
    # clock tests advance. Return their actual security expiry to the browser.
    from app.models import now

    expiry = now() + timedelta(minutes=5)
    return [
        PublicPhoto(
            id=photo.id,
            url=storage.read_url(cast(str, photo.final_key)),
            expires_at=expiry,
            width=cast(int, photo.width),
            height=cast(int, photo.height),
        )
        for photo in verified
    ]


def _summary(
    listing: Listing,
    demo: bool,
    check_in: date | None = None,
    check_out: date | None = None,
) -> PublicSummary:
    return PublicSummary(
        id=listing.id,
        title=cast(str, listing.title),
        destination=cast(str, listing.destination),
        property_type=cast(str, listing.property_type),
        capacity=cast(int, listing.capacity),
        bedrooms=cast(int, listing.bedrooms),
        beds=cast(int, listing.beds),
        baths=cast(int, listing.baths),
        nightly_minor=cast(int, listing.nightly_minor),
        cleaning_minor=cast(int, listing.cleaning_minor),
        booking_mode=cast(Literal["instant", "request"], listing.booking_mode),
        photos=_photos(listing, cover_only=True),
        stay_price=pricing.price(listing, check_in, check_out)
        if check_in and check_out
        else None,
        demo_label=DEMO_LABEL if demo else None,
    )


def browse(
    db: Session,
    destination: str = "",
    check_in: date | None = None,
    check_out: date | None = None,
    guests: int = 1,
    limit: int = 20,
    cursor: UUID | None = None,
) -> PublicListings:
    if (check_in is None) != (check_out is None):
        raise invalid_date("Supply both check-in and checkout dates.", "check_out")
    if check_in is not None and check_out is not None:
        stay_range(check_in, check_out)
    with db.begin():
        now = business_time.at(db)
        criteria: list[Any] = [
            Listing.status == "published",
            Listing.capacity >= guests,
        ]
        if destination.strip():
            criteria.append(
                Listing.destination.icontains(destination.strip(), autoescape=True)
            )
        local_day = sql_cast(func.timezone(Listing.timezone, now), Date)
        if check_in is not None and check_out is not None:
            candidates = db.execute(
                select(func.count(), func.min(local_day), func.max(local_day))
                .select_from(Listing)
                .where(*criteria)
            ).one()
            if (candidates[0] and check_in < candidates[1]) or (
                not candidates[0] and check_in < now.date()
            ):
                raise invalid_date(
                    "Check-in cannot be in the matching listings' local past."
                )
            latest_local_day = candidates[2] if candidates[0] else now.date()
            if check_in > latest_local_day + timedelta(days=730):
                raise invalid_date("Check-in must be within 730 days.")
            criteria += [
                local_day <= check_in,
                local_day + 730 >= check_in,
                ~select(CalendarEntry.id)
                .where(
                    CalendarEntry.listing_id == Listing.id,
                    CalendarEntry.active,
                    CalendarEntry.check_in < check_out,
                    CalendarEntry.check_out > check_in,
                )
                .exists(),
            ]
        query = select(Listing).where(*criteria).order_by(Listing.id).limit(limit + 1)
        if cursor:
            query = query.where(Listing.id > cursor)
        rows = list(db.scalars(query))
        demos = (
            set(
                db.scalars(
                    select(DemoImport.listing_id).where(
                        DemoImport.listing_id.in_([row.id for row in rows])
                    )
                )
            )
            if rows
            else set()
        )
        results = []
        for row in rows[:limit]:
            if check_in is not None and check_out is not None:
                try:
                    pricing.check_stay(row, check_in, check_out, guests, as_of=now)
                except ApiError:
                    continue
            results.append(_summary(row, row.id in demos, check_in, check_out))
        result = PublicListings(
            items=results,
            next_cursor=str(rows[limit - 1].id) if len(rows) > limit else None,
        )
    return result


def detail(db: Session, listing_id: UUID) -> PublicListingResponse:
    with db.begin():
        listing = _published(db, listing_id)
        demo = (
            db.scalar(
                select(DemoImport.demo_key).where(DemoImport.listing_id == listing_id)
            )
            is not None
        )
        summary = _summary(listing, demo)
        host = db.get(User, listing.owner_id)
        assert host is not None
        result = PublicListingResponse(
            listing=PublicDetail(
                **{**summary.model_dump(), "photos": _photos(listing)},
                description=cast(str, listing.description),
                amenities=listing.amenities or [],
                house_rules=listing.house_rules or [],
                timezone=cast(str, listing.timezone),
                check_in_time=cast(str, listing.check_in_time),
                check_out_time=cast(str, listing.check_out_time),
                host_name=host.name,
                policy=pricing.policy(db, listing),
            )
        )
    return result


def photos(db: Session, listing_id: UUID) -> PublicPhotos:
    with db.begin():
        result = PublicPhotos(items=_photos(_published(db, listing_id)))
    return result


def availability(
    db: Session, listing_id: UUID, start: date, end: date
) -> AvailabilityResponse:
    with db.begin():
        listing = _published(db, listing_id)
        timezone = cast(str, listing.timezone)
        read_range(start, end, timezone)
        entries = db.scalars(
            select(CalendarEntry)
            .where(
                CalendarEntry.listing_id == listing_id,
                CalendarEntry.active,
                CalendarEntry.check_in < end,
                CalendarEntry.check_out > start,
            )
            .order_by(CalendarEntry.check_in)
        )
        result = AvailabilityResponse(
            listing_id=listing_id,
            timezone=timezone,
            start=start,
            end=end,
            unavailable=[
                StayDates(check_in=row.check_in, check_out=row.check_out)
                for row in entries
            ],
        )
    return result


def quote(db: Session, body: QuoteInput) -> QuoteResponse:
    with db.begin():
        listing = _published(db, body.listing_id)
        result = QuoteResponse(
            quote=pricing.quote(
                db,
                listing,
                body.check_in,
                body.check_out,
                body.guests,
                as_of=business_time.at(db),
            )
        )
    return result
