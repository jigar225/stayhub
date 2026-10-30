from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app import discovery_service
from app.discovery_schemas import (
    AvailabilityResponse,
    PublicListingResponse,
    PublicListings,
    PublicPhotos,
    QuoteInput,
    QuoteResponse,
)
from app.listing_routes import DB

router = APIRouter(prefix="/api/v1")


@router.get("/listings", response_model=PublicListings)
def browse(
    db: DB,
    destination: Annotated[str, Query(max_length=100)] = "",
    check_in: date | None = None,
    check_out: date | None = None,
    guests: Annotated[int, Query(ge=1, le=30)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: UUID | None = None,
) -> PublicListings:
    return discovery_service.browse(
        db, destination, check_in, check_out, guests, limit, cursor
    )


@router.get("/listings/{listing_id}", response_model=PublicListingResponse)
def detail(listing_id: UUID, db: DB) -> PublicListingResponse:
    return discovery_service.detail(db, listing_id)


@router.get("/listings/{listing_id}/photos", response_model=PublicPhotos)
def photos(listing_id: UUID, db: DB) -> PublicPhotos:
    return discovery_service.photos(db, listing_id)


@router.get("/listings/{listing_id}/availability", response_model=AvailabilityResponse)
def availability(
    listing_id: UUID, start: date, end: date, db: DB
) -> AvailabilityResponse:
    return discovery_service.availability(db, listing_id, start, end)


@router.post("/booking-quotes", response_model=QuoteResponse)
def quote(body: QuoteInput, db: DB) -> QuoteResponse:
    return discovery_service.quote(db, body)
