from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

from app.categories import StayCategory
from app.schemas import StrictModel

ShortText = Annotated[str, Field(min_length=1, max_length=60)]
RuleText = Annotated[str, Field(min_length=1, max_length=500)]


class DraftFields(StrictModel):
    property_type: Literal["apartment", "house", "room"] | None = None
    address: str | None = Field(default=None, min_length=1, max_length=300)
    latitude: float | None = Field(default=None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(default=None, ge=-180, le=180, allow_inf_nan=False)
    destination: str | None = Field(default=None, min_length=1, max_length=100)
    timezone: str | None = Field(default=None, max_length=100)
    capacity: StrictInt | None = Field(default=None, ge=1, le=30)
    bedrooms: StrictInt | None = Field(default=None, ge=0, le=20)
    beds: StrictInt | None = Field(default=None, ge=1, le=30)
    baths: StrictInt | None = Field(default=None, ge=1, le=20)
    title: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, min_length=1, max_length=5000)
    categories: list[StayCategory] = Field(default_factory=list, max_length=9)
    amenities: list[ShortText] | None = Field(default=None, max_length=30)
    house_rules: list[RuleText] | None = Field(default=None, max_length=20)
    nightly_minor: StrictInt | None = Field(default=None, ge=100, le=10000000)
    cleaning_minor: StrictInt | None = Field(default=None, ge=0, le=1000000)
    policy_id: UUID | None = None
    booking_mode: Literal["instant", "request"] | None = None
    check_in_time: str | None = Field(
        default="15:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$"
    )
    check_out_time: str | None = Field(
        default="11:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$"
    )

    @field_validator("latitude", "longitude", mode="before")
    @classmethod
    def numeric_coordinates(cls, value: object) -> object:
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, (int, float))
        ):
            raise ValueError("Coordinates must be numbers.")
        return value

    @model_validator(mode="after")
    def paired_coordinates(self) -> "DraftFields":
        supplied = self.model_fields_set & {"latitude", "longitude"}
        if supplied and supplied != {"latitude", "longitude"}:
            raise ValueError("Send latitude and longitude together.")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Coordinates must both be numbers or both null.")
        return self

    @field_validator(
        "property_type",
        "address",
        "destination",
        "timezone",
        "title",
        "description",
        "booking_mode",
        "check_in_time",
        "check_out_time",
        mode="before",
    )
    @classmethod
    def normalize_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError):
                raise ValueError("Use a supported IANA timezone.") from None
        return value

    @field_validator("amenities", "house_rules", mode="before")
    @classmethod
    def trim_entries(cls, value: object) -> object:
        if isinstance(value, list):
            return [
                entry.strip() if isinstance(entry, str) else entry for entry in value
            ]
        return value

    @field_validator("amenities", "house_rules", "categories")
    @classmethod
    def unique_entries(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("Entries must be unique.")
        return value


class ListingPatch(DraftFields):
    version: StrictInt = Field(ge=1)


class VersionInput(StrictModel):
    version: StrictInt = Field(ge=1)


class PhotoOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    order: int
    content_type: str
    bytes: int
    width: int
    height: int


class ListingOutput(DraftFields):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: Literal["draft", "published", "unlisted"]
    version: int
    created_at: datetime
    updated_at: datetime
    photos: list[PhotoOutput]


class ListingResponse(BaseModel):
    listing: ListingOutput


class ListingsResponse(BaseModel):
    items: list[ListingOutput]
    next_cursor: str | None


class PolicyOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    version: int
    terms: str


class TimezoneOption(BaseModel):
    value: str
    label: str


class TimezonesResponse(BaseModel):
    items: list[TimezoneOption]


class PoliciesResponse(BaseModel):
    items: list[PolicyOutput]


class UploadIntentInput(StrictModel):
    content_type: Literal["image/jpeg", "image/png", "image/webp"]
    bytes: StrictInt = Field(ge=1, le=10485760)


class UploadAuthorization(BaseModel):
    method: Literal["PUT"] = "PUT"
    url: str
    headers: dict[str, str]


class UploadIntentResponse(BaseModel):
    photo_id: UUID
    upload: UploadAuthorization
    expires_in: Literal[300] = 300


class CompleteResponse(ListingResponse):
    photo: PhotoOutput


class PhotoOrderInput(VersionInput):
    photo_ids: list[UUID] = Field(max_length=20)


class PhotoReadResponse(BaseModel):
    url: str
    expires_in: Literal[300] = 300


class EmptyInput(StrictModel):
    pass
