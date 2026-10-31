"""Double-blind review transport, with no counterpart-presence leak."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, StrictInt, field_validator

from app.schemas import StrictModel

CATEGORIES = (
    "cleanliness",
    "accuracy",
    "check_in",
    "communication",
    "location",
    "value",
)


class ReviewInput(StrictModel):
    text: str = Field(min_length=1, max_length=3000)
    overall: StrictInt | None = Field(default=None, ge=1, le=5)
    categories: dict[str, StrictInt] = Field(default_factory=dict)

    @field_validator("text")
    @classmethod
    def trim(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Write a review before submitting.")
        return value.strip()

    @field_validator("categories")
    @classmethod
    def category_values(cls, value: dict[str, int]) -> dict[str, int]:
        if any(k not in CATEGORIES or v < 1 or v > 5 for k, v in value.items()):
            raise ValueError("Category ratings must be whole numbers from 1 to 5.")
        return value


class ReviewOutput(BaseModel):
    id: UUID
    author_role: Literal["guest", "host"]
    author_name: str
    text: str
    overall: int | None
    categories: dict[str, int]
    submitted_at: datetime
    published_at: datetime | None


class PartyReviews(BaseModel):
    reservation_id: UUID
    listing_title: str
    role: Literal["guest", "host"]
    eligible: bool
    deadline: datetime | None
    own: ReviewOutput | None
    counterpart: ReviewOutput | None
    status: Literal["not_completed", "open", "submitted", "published", "closed"]


class ListingReviews(BaseModel):
    items: list[ReviewOutput]
    average: float | None
    count: int
    next_cursor: str | None


class HostReviewOutput(ReviewOutput):
    listing_id: UUID
    listing_title: str


class HostReviews(BaseModel):
    items: list[HostReviewOutput]
    average: float | None
    count: int
    next_cursor: str | None
