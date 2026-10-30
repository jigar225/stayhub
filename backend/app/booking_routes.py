"""Thin reservation HTTP adapters; transactions and decisions live in services."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from starlette.responses import JSONResponse, Response

from app import booking_queries, booking_service
from app.booking_schemas import (
    DeclineInput,
    HostTodayOutput,
    PayInput,
    ReservationResponse,
    ReservationsResponse,
)
from app.discovery_schemas import PublicPhotos
from app.errors import ApiError
from app.listing_routes import DB, actor_context, mutation_guard
from app.listing_schemas import EmptyInput

router = APIRouter(prefix="/api/v1")
PageLimit = Annotated[int, Query(ge=1, le=100)]


@router.post("/reservations", response_model=ReservationResponse, status_code=201)
def pay(body: PayInput, request: Request, db: DB) -> Response | ReservationResponse:
    return wire_result(
        booking_service.pay(
            db,
            actor_context(request),
            body,
            request.headers.get("idempotency-key", ""),
            guard=mutation_guard(request),
        )
    )


@router.get("/me/reservations", response_model=ReservationsResponse)
def guest_reservations(
    request: Request,
    db: DB,
    category: Literal["all", "pending", "upcoming", "past", "cancelled"] = "all",
    limit: PageLimit = 20,
    cursor: UUID | None = None,
) -> ReservationsResponse:
    return booking_queries.guest_list(
        db, actor_context(request), category, limit, cursor
    )


@router.get("/host/reservations", response_model=ReservationsResponse)
def host_reservations(
    request: Request,
    db: DB,
    state: Literal[
        "pending",
        "confirmed",
        "checked_in",
        "completed",
        "declined",
        "cancelled_by_guest",
        "cancelled_by_host",
    ]
    | None = None,
    limit: PageLimit = 20,
    cursor: UUID | None = None,
) -> ReservationsResponse:
    return booking_queries.host_list(db, actor_context(request), state, limit, cursor)


@router.get("/host/today", response_model=HostTodayOutput)
def host_today(
    request: Request, db: DB, limit: PageLimit = 20, cursor: UUID | None = None
) -> HostTodayOutput:
    return booking_queries.today(db, actor_context(request), limit, cursor)


@router.get("/reservations/{reservation_id}", response_model=ReservationResponse)
def detail(reservation_id: UUID, request: Request, db: DB) -> ReservationResponse:
    return booking_queries.detail(db, actor_context(request), reservation_id)


@router.get("/reservations/{reservation_id}/photos", response_model=PublicPhotos)
def photos(reservation_id: UUID, request: Request, db: DB) -> PublicPhotos:
    return booking_queries.photos(db, actor_context(request), reservation_id)


def decision_result(
    result: ReservationResponse | booking_service.CommittedFailure,
) -> ReservationResponse:
    if isinstance(result, booking_service.CommittedFailure):
        raise ApiError(409, result.code, result.message)
    return result


@router.post(
    "/host/reservations/{reservation_id}/accept", response_model=ReservationResponse
)
def accept(
    reservation_id: UUID, body: EmptyInput, request: Request, db: DB
) -> Response | ReservationResponse:
    return wire_result(
        decision_result(
            booking_service.host_decision(
                db,
                actor_context(request),
                reservation_id,
                "accept",
                None,
                request.headers.get("idempotency-key", ""),
                guard=mutation_guard(request),
            )
        )
    )


@router.post(
    "/host/reservations/{reservation_id}/decline", response_model=ReservationResponse
)
def decline(
    reservation_id: UUID, body: DeclineInput, request: Request, db: DB
) -> Response | ReservationResponse:
    return wire_result(
        decision_result(
            booking_service.host_decision(
                db,
                actor_context(request),
                reservation_id,
                "decline",
                body,
                request.headers.get("idempotency-key", ""),
                guard=mutation_guard(request),
            )
        )
    )


def wire_result(result: ReservationResponse) -> Response | ReservationResponse:
    # Bypass response-model expansion for historical successful idempotency
    # responses. The stored JSON shape and original status remain unchanged.
    if result._replay_body is not None:
        return JSONResponse(result._replay_body, status_code=result._replay_status)
    return result
