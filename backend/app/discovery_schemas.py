from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.schemas import StrictModel


class StayDates(StrictModel):
    check_in: date
    check_out: date


class BlockOutput(StayDates):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    kind: Literal["block"] = "block"


class BlockResponse(BaseModel):
    block: BlockOutput


class ReservationOccupancy(StayDates):
    id: UUID
    kind: Literal["reservation"] = "reservation"
    reservation_id: UUID
    state: Literal["pending", "confirmed", "checked_in", "completed"]
    code: str


class CalendarResponse(BaseModel):
    listing_id: UUID
    timezone: str
    start: date
    end: date
    items: list[BlockOutput | ReservationOccupancy]


class AvailabilityResponse(BaseModel):
    listing_id: UUID
    timezone: str
    start: date
    end: date
    unavailable: list[StayDates]


class PriceBreakdown(BaseModel):
    nights: int
    nightly_minor: int
    nights_minor: int
    cleaning_minor: int
    subtotal_minor: int
    guest_fee_minor: int
    total_minor: int
    currency: Literal["EUR"] = "EUR"


class PublicPhoto(BaseModel):
    id: UUID
    url: str
    expires_at: datetime
    width: int
    height: int


class PublicPhotos(BaseModel):
    items: list[PublicPhoto]


class PublicSummary(BaseModel):
    id: UUID
    title: str
    destination: str
    property_type: str
    capacity: int
    bedrooms: int
    beds: int
    baths: int
    nightly_minor: int
    cleaning_minor: int
    booking_mode: Literal["instant", "request"]
    photos: list[PublicPhoto]
    stay_price: PriceBreakdown | None
    demo_label: str | None


class PublicListings(BaseModel):
    items: list[PublicSummary]
    next_cursor: str | None


class PublicPolicy(BaseModel):
    id: UUID
    name: str
    version: int
    terms: str


class PublicDetail(PublicSummary):
    description: str
    amenities: list[str]
    house_rules: list[str]
    timezone: str
    check_in_time: str
    check_out_time: str
    host_name: str
    policy: PublicPolicy


class PublicListingResponse(BaseModel):
    listing: PublicDetail


class QuoteInput(StayDates):
    listing_id: UUID
    guests: StrictInt = Field(ge=1, le=30)


class Quote(PriceBreakdown):
    listing_id: UUID
    check_in: date
    check_out: date
    guests: int
    booking_mode: Literal["instant", "request"]
    policy: PublicPolicy
    scheduled_check_in: datetime
    scheduled_check_out: datetime
    expires_at: datetime
    quote_token: str


class QuoteResponse(BaseModel):
    quote: Quote
