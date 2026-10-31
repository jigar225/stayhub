import re
from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import ValidationError

from app import discovery_service
from app.categories import StayCategory
from app.discovery_filters import Amenity, BrowseFilters, PlaceGroup
from app.discovery_schemas import (
    AvailabilityResponse,
    PublicListingResponse,
    PublicListings,
    PublicPhotos,
    QuoteInput,
    QuoteResponse,
)
from app.errors import ApiError
from app.listing_routes import DB

router = APIRouter(prefix="/api/v1")


@router.get("/listings", response_model=PublicListings)
def browse(
    request: Request,
    db: DB,
    destination: Annotated[str, Query(max_length=100)] = "",
    check_in: date | None = None,
    check_out: date | None = None,
    guests: Annotated[int, Query(ge=1, le=30)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: UUID | None = None,
    category: StayCategory | None = None,
    place_group: PlaceGroup | None = None,
    min_price_minor: Annotated[int | None, Query(ge=0, le=10000000)] = None,
    max_price_minor: Annotated[int | None, Query(ge=0, le=10000000)] = None,
    min_bedrooms: Annotated[int | None, Query(ge=0, le=20)] = None,
    min_beds: Annotated[int | None, Query(ge=0, le=30)] = None,
    amenity: Annotated[list[Amenity] | None, Query(max_length=9)] = None,
    instant_book: Literal["true", "false"] | None = None,
) -> PublicListings:
    # A scalar query has one meaning: don't silently choose first/last repeated
    # values differently from the browser's URL parser. Amenity is the one set.
    scalar_fields = {
        "destination",
        "check_in",
        "check_out",
        "guests",
        "limit",
        "cursor",
        "category",
        "place_group",
        "min_price_minor",
        "max_price_minor",
        "min_bedrooms",
        "min_beds",
        "instant_book",
    }
    for field in scalar_fields:
        values = request.query_params.getlist(field)
        if len(values) > 1:
            raise ApiError(
                422,
                "validation_error",
                "Supply each search field once.",
                field_errors={field: "Repeated values are not allowed."},
            )
    for field in ("min_price_minor", "max_price_minor", "min_bedrooms", "min_beds"):
        value = request.query_params.get(field)
        if value is not None and not re.fullmatch(r"[0-9]+", value):
            raise ApiError(
                422,
                "validation_error",
                "Use whole nonnegative values.",
                field_errors={field: "Use a whole nonnegative integer."},
            )
    try:
        filters = BrowseFilters(
            place_group=place_group,
            min_price_minor=min_price_minor,
            max_price_minor=max_price_minor,
            min_bedrooms=min_bedrooms,
            min_beds=min_beds,
            amenity=amenity or [],
            instant_book=instant_book == "true",
        )
    except ValidationError as error:
        raise ApiError(
            422,
            "validation_error",
            "Check the highlighted filters.",
            field_errors={
                "max_price_minor": "Maximum nightly price must be at least the minimum."
            },
        ) from error
    return discovery_service.browse(
        db, destination, check_in, check_out, guests, limit, cursor, category, filters
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
