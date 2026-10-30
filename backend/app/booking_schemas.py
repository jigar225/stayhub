"""M4 transport values; identity and money never come from booking input."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    StrictInt,
    field_validator,
)

from app.discovery_schemas import PriceBreakdown, PublicPolicy
from app.financial_schemas import PayoutOutput
from app.schemas import StrictModel


class PayInput(StrictModel):
    quote_token: str = Field(min_length=1, max_length=16384)


class DeclineInput(StrictModel):
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ListingSnapshot(BaseModel):
    title: str
    destination: str
    property_type: str
    description: str
    amenities: list[str]
    house_rules: list[str]
    host_name: str


class PolicySnapshot(PublicPolicy):
    definition: dict[str, object]


class PaymentOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    amount_minor: int
    currency: Literal["EUR"]
    paid_at: datetime


class RefundOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    amount_minor: int
    nights_minor: int
    cleaning_minor: int
    guest_fee_minor: int
    reason: str
    refunded_at: datetime


class ReservationOutput(BaseModel):
    id: UUID
    code: str
    listing_id: UUID
    guest_id: UUID
    host_id: UUID
    state: Literal[
        "pending",
        "confirmed",
        "checked_in",
        "completed",
        "declined",
        "cancelled_by_guest",
        "cancelled_by_host",
    ]
    reason: str | None
    booking_mode: Literal["instant", "request"]
    check_in: date
    check_out: date
    guests: int
    timezone: str
    scheduled_check_in: datetime
    scheduled_check_out: datetime
    created_at: datetime
    request_deadline: datetime | None
    listing_snapshot: ListingSnapshot
    policy: PolicySnapshot
    price: PriceBreakdown
    host_fee_minor: int
    host_entitlement_minor: int
    platform_entitlement_minor: int
    payment: PaymentOutput
    refund: RefundOutput | None
    financial_version: int = 1
    effective_host_fee_minor: int = 0
    cancelled_at: datetime | None = None
    payout: PayoutOutput | None = None


class ReservationResponse(BaseModel):
    _replay_body: dict[str, object] | None = PrivateAttr(default=None)
    _replay_status: int = PrivateAttr(default=200)
    reservation: ReservationOutput

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, ReservationResponse)
            and self.model_dump() == other.model_dump()
        )


class ReservationsResponse(BaseModel):
    items: list[ReservationOutput]
    next_cursor: str | None


class HostTodayOutput(BaseModel):
    pending: list[ReservationOutput]
    upcoming: list[ReservationOutput]
    hosting: list[ReservationOutput] = []
    checkouts: list[ReservationOutput] = []
    next_cursor: str | None


class QuoteClaims(PriceBreakdown):
    """Validate signed claims before any claim is used in a database query."""

    model_config = ConfigDict(extra="forbid")
    listing_id: UUID
    listing_version: StrictInt = Field(ge=1)
    check_in: date
    check_out: date
    guests: StrictInt = Field(ge=1, le=30)
    booking_mode: Literal["instant", "request"]
    policy: PublicPolicy
    scheduled_check_in: datetime
    scheduled_check_out: datetime
    iat: StrictInt
    exp: StrictInt
    iss: str
    aud: Literal["stayhub-booking-quote"]
    purpose: Literal["booking_quote"]
