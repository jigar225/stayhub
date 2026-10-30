"""Integer EUR quote calculation shared by dated discovery and quote creation."""

from datetime import date, datetime, timedelta
from typing import Literal, cast
from uuid import UUID

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import business_time
from app.config import get_settings
from app.date_rules import invalid_date, scheduled, stay_range
from app.discovery_schemas import PriceBreakdown, PublicPolicy, Quote
from app.errors import ApiError
from app.models import CalendarEntry, CancellationPolicy, Listing

POLICY_TERMS = {
    "Flexible": "100% of nights and guest service fee refunded at least 24 hours before check-in; otherwise 0%. Cleaning refunded before check-in.",
    "Moderate": "100% at least 5 days before check-in; 50% at least 24 hours before; otherwise 0%. Applies to nights and guest service fee. Cleaning refunded before check-in.",
    "Firm": "100% at least 30 days before check-in; 50% at least 7 days before; otherwise 0%. Applies to nights and guest service fee. Cleaning refunded before check-in.",
    "Strict": "100% within 48 hours after booking and before check-in; otherwise 50% at least 14 days before check-in, then 0%. Applies to nights and guest service fee. Cleaning refunded before check-in.",
}


def price(listing: Listing, check_in: date, check_out: date) -> PriceBreakdown:
    nights = (check_out - check_in).days
    assert listing.nightly_minor is not None and listing.cleaning_minor is not None
    nights_minor = nights * listing.nightly_minor
    subtotal = nights_minor + listing.cleaning_minor
    fee = (subtotal * 14 + 50) // 100
    return PriceBreakdown(
        nights=nights,
        nightly_minor=listing.nightly_minor,
        nights_minor=nights_minor,
        cleaning_minor=listing.cleaning_minor,
        subtotal_minor=subtotal,
        guest_fee_minor=fee,
        total_minor=subtotal + fee,
    )


def policy(db: Session, listing: Listing) -> PublicPolicy:
    assert listing.policy_id is not None
    row = db.get(CancellationPolicy, listing.policy_id)
    assert row is not None
    return PublicPolicy(
        id=row.id, name=row.name, version=row.version, terms=POLICY_TERMS[row.name]
    )


def occupancy_exists(
    db: Session, listing_id: UUID, check_in: date, check_out: date
) -> bool:
    return (
        db.scalar(
            select(CalendarEntry.id)
            .where(
                CalendarEntry.listing_id == listing_id,
                CalendarEntry.active,
                CalendarEntry.check_in < check_out,
                CalendarEntry.check_out > check_in,
            )
            .limit(1)
        )
        is not None
    )


def check_stay(
    listing: Listing,
    check_in: date,
    check_out: date,
    guests: int,
    *,
    as_of: datetime | None = None,
) -> tuple[datetime, datetime]:
    assert listing.timezone is not None and listing.capacity is not None
    assert listing.check_in_time is not None and listing.check_out_time is not None
    now = as_of or business_time.now()
    stay_range(check_in, check_out, listing.timezone, as_of=now)
    if guests > listing.capacity:
        raise invalid_date("The guest count exceeds this listing's capacity.", "guests")
    arrival = scheduled(check_in, listing.check_in_time, listing.timezone)
    departure = scheduled(check_out, listing.check_out_time, listing.timezone)
    if listing.booking_mode == "instant" and arrival <= now:
        raise invalid_date(
            "Scheduled check-in has already started. Choose a later check-in date."
        )
    if listing.booking_mode == "request" and arrival < now + timedelta(hours=24):
        raise invalid_date(
            "Request stays require at least 24 hours before scheduled check-in."
        )
    return arrival, departure


def quote(
    db: Session,
    listing: Listing,
    check_in: date,
    check_out: date,
    guests: int,
    *,
    as_of: datetime | None = None,
) -> Quote:
    issued = as_of or business_time.now()
    arrival, departure = check_stay(listing, check_in, check_out, guests, as_of=issued)
    if occupancy_exists(db, listing.id, check_in, check_out):
        raise ApiError(
            409,
            "availability_conflict",
            "This listing is not available for the whole stay.",
        )
    breakdown = price(listing, check_in, check_out)
    terms = policy(db, listing)
    expiry = issued + timedelta(minutes=10)
    settings = get_settings()
    claims = {
        **breakdown.model_dump(),
        "listing_id": str(listing.id),
        "listing_version": listing.version,
        "check_in": str(check_in),
        "check_out": str(check_out),
        "guests": guests,
        "booking_mode": listing.booking_mode,
        "policy": terms.model_dump(mode="json"),
        "scheduled_check_in": arrival.isoformat(),
        "scheduled_check_out": departure.isoformat(),
        "iat": issued,
        "exp": expiry,
        "iss": settings.jwt_issuer,
        "aud": "stayhub-booking-quote",
        "purpose": "booking_quote",
    }
    token = jwt.encode(
        claims, settings.jwt_secret.get_secret_value(), algorithm="HS256"
    )
    return Quote(
        **breakdown.model_dump(),
        listing_id=listing.id,
        check_in=check_in,
        check_out=check_out,
        guests=guests,
        booking_mode=cast(Literal["instant", "request"], listing.booking_mode),
        policy=terms,
        scheduled_check_in=arrival,
        scheduled_check_out=departure,
        expires_at=expiry,
        quote_token=token,
    )
