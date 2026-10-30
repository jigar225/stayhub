from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app import auth_service, listing_service
from app.db import get_db
from app.listing_schemas import (
    CompleteResponse,
    EmptyInput,
    ListingPatch,
    ListingResponse,
    ListingsResponse,
    PhotoOrderInput,
    PhotoReadResponse,
    PoliciesResponse,
    UploadIntentInput,
    UploadIntentResponse,
    VersionInput,
)
from app.security import require_origin

router = APIRouter(prefix="/api/v1/host")
DB = Annotated[Session, Depends(get_db)]


def actor_context(request: Request) -> auth_service.AccessContext:
    return auth_service.access_context(request.headers.get("authorization", ""))


def mutation_guard(request: Request) -> Callable[[], None]:
    # Run after the service's live role/owner checks, preserving HTTP guard order.
    def check() -> None:
        require_origin(request)

    return check


@router.get("/cancellation-policies", response_model=PoliciesResponse)
def policies(request: Request, db: DB) -> PoliciesResponse:
    return listing_service.policies(db, actor_context(request))


@router.post("/listings", response_model=ListingResponse, status_code=201)
def create_listing(body: EmptyInput, request: Request, db: DB) -> ListingResponse:
    actor = actor_context(request)
    return listing_service.create_listing(db, actor, guard=mutation_guard(request))


@router.get("/listings", response_model=ListingsResponse)
def list_listings(
    request: Request,
    db: DB,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: UUID | None = None,
) -> ListingsResponse:
    return listing_service.list_listings(db, actor_context(request), limit, cursor)


@router.get("/listings/{listing_id}", response_model=ListingResponse)
def get_listing(listing_id: UUID, request: Request, db: DB) -> ListingResponse:
    return listing_service.get_listing(db, actor_context(request), listing_id)


@router.patch("/listings/{listing_id}", response_model=ListingResponse)
def update_listing(
    listing_id: UUID, body: ListingPatch, request: Request, db: DB
) -> ListingResponse:
    actor = actor_context(request)
    return listing_service.update_listing(
        db, actor, listing_id, body, guard=mutation_guard(request)
    )


@router.post("/listings/{listing_id}/publish", response_model=ListingResponse)
def publish(
    listing_id: UUID, body: VersionInput, request: Request, db: DB
) -> ListingResponse:
    actor = actor_context(request)
    return listing_service.publish(
        db, actor, listing_id, body.version, guard=mutation_guard(request)
    )


@router.post("/listings/{listing_id}/unlist", response_model=ListingResponse)
def unlist(
    listing_id: UUID, body: VersionInput, request: Request, db: DB
) -> ListingResponse:
    actor = actor_context(request)
    return listing_service.unlist(
        db, actor, listing_id, body.version, guard=mutation_guard(request)
    )


@router.post(
    "/listings/{listing_id}/photos/upload-intents",
    response_model=UploadIntentResponse,
    status_code=201,
)
def upload_intent(
    listing_id: UUID, body: UploadIntentInput, request: Request, db: DB
) -> UploadIntentResponse:
    actor = actor_context(request)
    return listing_service.create_upload_intent(
        db, actor, listing_id, body, guard=mutation_guard(request)
    )


@router.post(
    "/listings/{listing_id}/photos/{photo_id}/complete", response_model=CompleteResponse
)
def complete(
    listing_id: UUID, photo_id: UUID, body: EmptyInput, request: Request, db: DB
) -> CompleteResponse:
    actor = actor_context(request)
    return listing_service.complete_photo(
        db, actor, listing_id, photo_id, guard=mutation_guard(request)
    )


@router.delete(
    "/listings/{listing_id}/photos/{photo_id}", response_model=ListingResponse
)
def delete_photo(
    listing_id: UUID, photo_id: UUID, request: Request, db: DB
) -> ListingResponse:
    actor = actor_context(request)
    return listing_service.delete_photo(
        db, actor, listing_id, photo_id, guard=mutation_guard(request)
    )


@router.patch("/listings/{listing_id}/photos/order", response_model=ListingResponse)
def order_photos(
    listing_id: UUID, body: PhotoOrderInput, request: Request, db: DB
) -> ListingResponse:
    actor = actor_context(request)
    return listing_service.order_photos(
        db, actor, listing_id, body, guard=mutation_guard(request)
    )


@router.get(
    "/listings/{listing_id}/photos/{photo_id}/read", response_model=PhotoReadResponse
)
def read_photo(
    listing_id: UUID, photo_id: UUID, request: Request, db: DB
) -> PhotoReadResponse:
    return listing_service.read_photo(db, actor_context(request), listing_id, photo_id)
