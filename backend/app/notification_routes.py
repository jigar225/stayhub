"""In-app notification transport; all private state is recipient scoped."""

from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app import notification_service
from app.listing_routes import DB, actor_context, mutation_guard
from app.listing_schemas import EmptyInput

router = APIRouter(prefix="/api/v1/me/notifications")


class ReadAll(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cutoff: int = Field(ge=0)


@router.get("")
def notifications(
    request: Request,
    db: DB,
    before: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> dict[str, Any]:
    return notification_service.page(db, actor_context(request), before, limit)


@router.post("/read-all")
def read_all(body: ReadAll, request: Request, db: DB) -> dict[str, bool]:
    return notification_service.acknowledge(
        db, actor_context(request), cutoff=body.cutoff, guard=mutation_guard(request)
    )


@router.post("/{notification_id}/read")
def read_one(
    notification_id: int, body: EmptyInput, request: Request, db: DB
) -> dict[str, bool]:
    return notification_service.acknowledge(
        db,
        actor_context(request),
        notification_id=notification_id,
        guard=mutation_guard(request),
    )
