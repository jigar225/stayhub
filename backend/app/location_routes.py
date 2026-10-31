"""Dedicated location routes, keeping discovery/search contracts separate."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import Field, field_validator
from sqlalchemy.orm import Session

from app import auth_service, location_service
from app.db import get_db
from app.schemas import StrictModel
from app.security import require_origin

router = APIRouter(prefix="/api/v1")
DB = Annotated[Session, Depends(get_db)]


class AutocompleteInput(StrictModel):
    query: str = Field(min_length=3, max_length=200)

    @field_validator("query", mode="before")
    @classmethod
    def clean_query(cls, value: object) -> object:
        if isinstance(value, str):
            if len(value) > 200:
                raise ValueError("Use at most 200 characters.")
            return value.strip()
        return value


@router.post("/host/location/autocomplete")
def autocomplete(
    body: AutocompleteInput, request: Request, db: DB
) -> dict[str, object]:
    actor = auth_service.access_context(request.headers.get("authorization", ""))
    require_origin(request)
    items = location_service.autocomplete(db, actor, body.query)
    return {
        "items": [item.model_dump() for item in items],
        "attribution": "Powered by Geoapify",
    }


@router.get("/listings/{listing_id}/location")
def public_location(listing_id: UUID, db: DB) -> dict[str, object]:
    return location_service.public_location(db, listing_id)
