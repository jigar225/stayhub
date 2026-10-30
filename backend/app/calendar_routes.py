from datetime import date
from uuid import UUID

from fastapi import APIRouter, Request

from app import calendar_service
from app.discovery_schemas import BlockResponse, CalendarResponse, StayDates
from app.listing_routes import DB, actor_context, mutation_guard

router = APIRouter(prefix="/api/v1/host/listings")


@router.get("/{listing_id}/calendar", response_model=CalendarResponse)
def calendar(
    listing_id: UUID, start: date, end: date, request: Request, db: DB
) -> CalendarResponse:
    return calendar_service.calendar(db, actor_context(request), listing_id, start, end)


@router.post("/{listing_id}/blocks", response_model=BlockResponse, status_code=201)
def create_block(
    listing_id: UUID, body: StayDates, request: Request, db: DB
) -> BlockResponse:
    return calendar_service.create_block(
        db, actor_context(request), listing_id, body, guard=mutation_guard(request)
    )


@router.delete("/{listing_id}/blocks/{block_id}", status_code=204)
def remove_block(listing_id: UUID, block_id: UUID, request: Request, db: DB) -> None:
    calendar_service.remove_block(
        db, actor_context(request), listing_id, block_id, guard=mutation_guard(request)
    )
