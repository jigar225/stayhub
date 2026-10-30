"""Thin M5 adapters; financial decisions/transactions remain in services."""

from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request
from starlette.responses import Response

from app import cancellation_service, clock_service, financial_queries
from app.booking_routes import decision_result, wire_result
from app.booking_schemas import DeclineInput, ReservationResponse
from app.booking_service import CommittedFailure
from app.errors import ApiError
from app.financial_schemas import (
    AdvanceInput,
    AdvanceResponse,
    BusinessTimeResponse,
    CancelInput,
    CancellationQuoteResponse,
    ClockOutput,
    EarningsResponse,
    EventsResponse,
    PayoutsResponse,
    SweepInput,
    SweepResponse,
)
from app.listing_routes import DB, actor_context, mutation_guard
from app.listing_schemas import EmptyInput

router = APIRouter(prefix="/api/v1")
Limit = Annotated[int, Query(ge=1, le=100)]
Status = Literal["held", "scheduled", "paid", "cancelled"]


@router.get("/business-time", response_model=BusinessTimeResponse)
def public_time(db: DB) -> BusinessTimeResponse:
    return clock_service.public_time(db)


@router.post(
    "/reservations/{reservation_id}/cancellation-quote",
    response_model=CancellationQuoteResponse,
)
def preview(
    reservation_id: UUID, body: EmptyInput, request: Request, db: DB
) -> CancellationQuoteResponse:
    result = cancellation_service.preview(
        db, actor_context(request), reservation_id, mutation_guard(request)
    )
    if isinstance(result, CommittedFailure):
        raise ApiError(409, result.code, result.message)
    return result


@router.post(
    "/reservations/{reservation_id}/cancel", response_model=ReservationResponse
)
def guest_cancel(
    reservation_id: UUID, body: CancelInput, request: Request, db: DB
) -> Response | ReservationResponse:
    return wire_result(
        decision_result(
            cancellation_service.cancel(
                db,
                actor_context(request),
                reservation_id,
                body,
                request.headers.get("idempotency-key", ""),
                guard=mutation_guard(request),
            )
        )
    )


@router.post(
    "/host/reservations/{reservation_id}/cancel", response_model=ReservationResponse
)
def host_cancel(
    reservation_id: UUID, body: DeclineInput, request: Request, db: DB
) -> Response | ReservationResponse:
    return wire_result(
        decision_result(
            cancellation_service.cancel(
                db,
                actor_context(request),
                reservation_id,
                body,
                request.headers.get("idempotency-key", ""),
                host=True,
                guard=mutation_guard(request),
            )
        )
    )


@router.get("/host/payouts", response_model=PayoutsResponse)
def payouts(
    request: Request,
    db: DB,
    status: Status | None = None,
    limit: Limit = 20,
    cursor: UUID | None = None,
) -> PayoutsResponse:
    return financial_queries.payouts(db, actor_context(request), status, limit, cursor)


@router.get("/host/earnings", response_model=EarningsResponse)
def earnings(
    request: Request,
    db: DB,
    status: Status | None = None,
    limit: Limit = 20,
    cursor: UUID | None = None,
) -> EarningsResponse:
    return cast(
        EarningsResponse,
        financial_queries.payouts(
            db, actor_context(request), status, limit, cursor, earnings=True
        ),
    )


@router.get("/admin/events", response_model=EventsResponse)
def events(
    request: Request,
    db: DB,
    action: str | None = None,
    target_id: UUID | None = None,
    limit: Limit = 20,
    cursor: UUID | None = None,
) -> EventsResponse:
    return financial_queries.events(
        db, actor_context(request), action, target_id, limit, cursor
    )


@router.get("/admin/demo/clock", response_model=ClockOutput)
def clock(request: Request, db: DB) -> ClockOutput:
    return clock_service.clock(db, actor_context(request))


@router.post("/admin/demo/advance", response_model=AdvanceResponse)
def advance(body: AdvanceInput, request: Request, db: DB) -> AdvanceResponse:
    return clock_service.advance(
        db,
        actor_context(request),
        body,
        request.headers.get("idempotency-key", ""),
        mutation_guard(request),
    )


@router.post("/admin/demo/sweep", response_model=SweepResponse)
def admin_sweep(body: SweepInput, request: Request, db: DB) -> SweepResponse:
    return SweepResponse(
        sweep=clock_service.admin_sweep(
            db, actor_context(request), body.batch_size, mutation_guard(request)
        )
    )
