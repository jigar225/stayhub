"""Thin private messaging adapters; service layer owns complete transactions."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request

from app import message_service
from app.listing_routes import DB, actor_context, mutation_guard
from app.listing_schemas import EmptyInput
from app.message_schemas import (
    AttachmentInput,
    AttachmentIntent,
    AttachmentOutput,
    InboxPage,
    MessagePage,
    ReadInput,
    SendInput,
    SendOutput,
)

router = APIRouter(prefix="/api/v1")


@router.get("/conversations", response_model=InboxPage)
def inbox(
    request: Request,
    db: DB,
    role: Literal["guest", "host"] = "guest",
    cursor: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 30,
) -> InboxPage:
    return message_service.inbox(db, actor_context(request), role, cursor, limit)


@router.get("/reservations/{rid}/messages", response_model=MessagePage)
def history(
    rid: UUID,
    request: Request,
    db: DB,
    before: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 30,
) -> MessagePage:
    return message_service.history(db, actor_context(request), rid, before, limit)


@router.post("/reservations/{rid}/messages", response_model=SendOutput, status_code=201)
def send(rid: UUID, body: SendInput, request: Request, db: DB) -> SendOutput:
    return message_service.send(
        db,
        actor_context(request),
        rid,
        body,
        request.headers.get("idempotency-key", ""),
        mutation_guard(request),
    )


@router.post("/reservations/{rid}/messages/read")
def read(rid: UUID, body: ReadInput, request: Request, db: DB) -> dict[str, int]:
    return message_service.acknowledge(
        db, actor_context(request), rid, body, mutation_guard(request)
    )


@router.post(
    "/reservations/{rid}/messages/attachments",
    response_model=AttachmentIntent,
    status_code=201,
)
def intent(
    rid: UUID, body: AttachmentInput, request: Request, db: DB
) -> AttachmentIntent:
    return message_service.attachment_intent(
        db, actor_context(request), rid, body, mutation_guard(request)
    )


@router.post(
    "/reservations/{rid}/messages/attachments/{aid}/complete",
    response_model=AttachmentOutput,
)
def complete(
    rid: UUID, aid: UUID, body: EmptyInput, request: Request, db: DB
) -> AttachmentOutput:
    return message_service.complete_attachment(
        db, actor_context(request), rid, aid, mutation_guard(request)
    )
