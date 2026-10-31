"""Thin review HTTP adapters."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request

from app import review_service
from app.listing_routes import DB, actor_context, mutation_guard
from app.review_schemas import HostReviews, ListingReviews, PartyReviews, ReviewInput

router = APIRouter(prefix="/api/v1")


@router.get("/reservations/{reservation_id}/reviews", response_model=PartyReviews)
def party(reservation_id: UUID, request: Request, db: DB) -> PartyReviews:
    return review_service.party_reviews(db, actor_context(request), reservation_id)


@router.post(
    "/reservations/{reservation_id}/reviews",
    response_model=PartyReviews,
    status_code=201,
)
def submit(
    reservation_id: UUID, body: ReviewInput, request: Request, db: DB
) -> PartyReviews:
    return review_service.submit(
        db, actor_context(request), reservation_id, body, guard=mutation_guard(request)
    )


@router.get("/listings/{listing_id}/reviews", response_model=ListingReviews)
def public_reviews(
    listing_id: UUID,
    db: DB,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: UUID | None = None,
) -> ListingReviews:
    return review_service.listing_reviews(db, listing_id, limit, cursor)


@router.get("/host/reviews", response_model=HostReviews)
def received_reviews(
    request: Request,
    db: DB,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: UUID | None = None,
) -> HostReviews:
    return review_service.host_reviews(db, actor_context(request), limit, cursor)
