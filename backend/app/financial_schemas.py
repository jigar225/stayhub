"""Cancellation, payout, clock and audit API value schemas."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StrictInt

from app.schemas import StrictModel


class PayoutOutput(BaseModel):
    id: UUID
    reservation_id: UUID
    code: str
    listing_title: str
    host_id: UUID
    due_at: datetime
    gross_minor: int
    host_fee_minor: int
    net_minor: int
    status: Literal["held", "scheduled", "paid", "cancelled"]
    paid_at: datetime | None
    retained_cancellation: bool


class PayoutsResponse(BaseModel):
    items: list[PayoutOutput]
    next_cursor: str | None


class EarningsResponse(PayoutsResponse):
    totals: dict[str, int]


class CancellationAmounts(BaseModel):
    refund_percent: int
    nights_refund_minor: int
    cleaning_refund_minor: int
    guest_fee_refund_minor: int
    total_refund_minor: int
    retained_nights_minor: int
    retained_guest_fee_minor: int
    effective_host_fee_minor: int
    host_entitlement_minor: int
    platform_entitlement_minor: int


class CancellationPreview(CancellationAmounts):
    reservation_id: UUID
    state: str
    financial_version: int
    policy_name: str
    policy_version: int
    explanation: str
    expires_at: datetime
    confirmation_token: str


class CancellationQuoteResponse(BaseModel):
    preview: CancellationPreview


class CancelInput(StrictModel):
    confirmation_token: str = Field(min_length=1, max_length=16384)


class CancellationClaims(CancellationAmounts):
    model_config = {"extra": "forbid"}
    actor_id: UUID
    reservation_id: UUID
    state: str
    financial_version: StrictInt
    iat: StrictInt
    exp: StrictInt
    iss: str
    aud: Literal["stayhub-cancellation"]
    purpose: Literal["cancellation"]


class ClockOutput(BaseModel):
    business_now: datetime
    real_now: datetime
    offset_seconds: int
    version: int
    demo_mode: bool


class BusinessTimeResponse(BaseModel):
    business_now: datetime
    real_now: datetime


class AdvanceInput(StrictModel):
    seconds: StrictInt = Field(ge=1, le=31536000)


class SweepInput(StrictModel):
    batch_size: StrictInt = Field(default=100, ge=1, le=1000)


class SweepResult(BaseModel):
    scanned: int = 0
    expired: int = 0
    checked_in: int = 0
    completed: int = 0
    paid: int = 0
    deferred: int = 0
    has_more: bool = False


class SweepResponse(BaseModel):
    sweep: SweepResult


class AdvanceResponse(BaseModel):
    clock: ClockOutput
    sweep: SweepResult


class EventOutput(BaseModel):
    model_config = {"from_attributes": True}
    id: UUID
    actor_id: UUID | None
    system_identity: str | None
    action: str
    target_type: str
    target_id: UUID
    before: dict[str, Any] | None
    after: dict[str, Any]
    business_at: datetime
    recorded_at: datetime


class EventsResponse(BaseModel):
    items: list[EventOutput]
    next_cursor: str | None
