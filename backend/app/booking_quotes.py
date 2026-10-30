"""Strict quote authenticity and locked current-term validation; no transactions."""

import json
from datetime import datetime

import jwt
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app import pricing
from app.booking_schemas import QuoteClaims
from app.config import get_settings
from app.errors import ApiError
from app.models import Listing


def decode_quote(token: str) -> QuoteClaims:
    settings = get_settings()
    try:
        data = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            audience="stayhub-booking-quote",
            issuer=settings.jwt_issuer,
            options={
                "verify_exp": False,
                "verify_iat": False,
                "verify_nbf": False,
                "require": ["iat", "exp", "iss", "aud", "purpose"],
            },
        )
        claims = QuoteClaims.model_validate_json(json.dumps(data), strict=True)
        if (
            claims.scheduled_check_in.tzinfo is None
            or claims.scheduled_check_out.tzinfo is None
            or claims.exp <= claims.iat
        ):
            raise ValueError("quote schedule")
        return claims
    except (
        jwt.InvalidTokenError,
        ValidationError,
        ValueError,
        TypeError,
        OverflowError,
    ):
        raise ApiError(
            422,
            "invalid_quote",
            "This price quote is invalid. Check the price again.",
            field_errors={"quote_token": "Get a new price quote for these dates."},
        ) from None


def revalidate(
    db: Session, listing: Listing, claims: QuoteClaims, now: datetime
) -> tuple[datetime, datetime]:
    if now.timestamp() >= claims.exp:
        raise ApiError(
            409,
            "quote_expired",
            "Your price quote expired. Review a fresh price before paying.",
        )
    if now.timestamp() < claims.iat:
        raise ApiError(
            422,
            "invalid_quote",
            "This quote was issued in the future. Check the price again.",
        )
    if listing.status != "published" or listing.version != claims.listing_version:
        raise ApiError(
            409,
            "stale_quote",
            "This stay changed or is no longer published. Review a fresh price.",
        )
    arrival, departure = pricing.check_stay(
        listing, claims.check_in, claims.check_out, claims.guests, as_of=now
    )
    amounts = pricing.price(listing, claims.check_in, claims.check_out)
    same_price = all(
        getattr(claims, key) == value for key, value in amounts.model_dump().items()
    )
    if (
        not same_price
        or claims.booking_mode != listing.booking_mode
        or claims.policy != pricing.policy(db, listing)
        or claims.scheduled_check_in != arrival
        or claims.scheduled_check_out != departure
    ):
        raise ApiError(
            409,
            "stale_quote",
            "The stay price or terms changed. Review a fresh quote before paying.",
        )
    if pricing.occupancy_exists(db, listing.id, claims.check_in, claims.check_out):
        raise ApiError(
            409,
            "availability_conflict",
            "This stay is no longer available for all selected nights.",
        )
    return arrival, departure
