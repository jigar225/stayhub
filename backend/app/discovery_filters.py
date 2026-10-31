"""Read-only discovery filters over existing owner-declared listing fields."""

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import JSON, case, func, literal, select
from sqlalchemy import cast as sql_cast

from app.models import Listing

PlaceGroup = Literal["entire", "private"]
Amenity = Literal[
    "wifi",
    "kitchen",
    "air-conditioning",
    "heating",
    "washer",
    "dryer",
    "workspace",
    "free-parking",
    "pool",
]

# Match a complete declared amenity after trim/case/whitespace normalization.
# No substring, photo, geographic, or category inference. Original stored text
# remains untouched, including owner-defined amenities outside this vocabulary.
AMENITY_ALIASES: dict[Amenity, tuple[str, ...]] = {
    "wifi": ("wifi", "wi-fi"),
    "kitchen": ("kitchen",),
    "air-conditioning": ("air conditioning", "air-conditioning"),
    "heating": ("heating",),
    "washer": ("washer", "washing machine"),
    "dryer": ("dryer",),
    "workspace": ("workspace", "dedicated workspace"),
    "free-parking": ("free parking", "free-parking"),
    "pool": ("pool", "swimming pool"),
}


class BrowseFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    place_group: PlaceGroup | None = None
    min_price_minor: int | None = Field(default=None, ge=0, le=10000000, strict=True)
    max_price_minor: int | None = Field(default=None, ge=0, le=10000000, strict=True)
    min_bedrooms: int | None = Field(default=None, ge=0, le=20, strict=True)
    min_beds: int | None = Field(default=None, ge=0, le=30, strict=True)
    amenity: list[Amenity] = Field(default_factory=list, max_length=9)
    instant_book: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def price_order(self) -> Self:
        if (
            self.min_price_minor is not None
            and self.max_price_minor is not None
            and self.min_price_minor > self.max_price_minor
        ):
            raise ValueError("Maximum nightly price must be at least the minimum.")
        return self

    def predicates(self) -> list[Any]:
        criteria: list[Any] = []
        if self.place_group == "entire":
            criteria.append(Listing.property_type.in_(["apartment", "house"]))
        elif self.place_group == "private":
            criteria.append(Listing.property_type == "room")
        if self.min_price_minor is not None:
            criteria.append(Listing.nightly_minor >= self.min_price_minor)
        if self.max_price_minor is not None:
            criteria.append(Listing.nightly_minor <= self.max_price_minor)
        if self.min_bedrooms is not None:
            criteria.append(Listing.bedrooms >= self.min_bedrooms)
        if self.min_beds is not None:
            criteria.append(Listing.beds >= self.min_beds)
        if self.instant_book:
            criteria.append(Listing.booking_mode == "instant")
        if self.amenity:
            # JSON null/SQL NULL are valid historical data; treat them as no
            # amenities rather than calling the array function on a scalar.
            source = case(
                (func.json_typeof(Listing.amenities) == "array", Listing.amenities),
                else_=sql_cast(literal("[]"), JSON),
            )
            declared = (
                func.json_array_elements_text(source)
                .table_valued("value")
                .render_derived(name="declared_amenity")
            )
            normalized = func.lower(
                func.btrim(func.regexp_replace(declared.c.value, r"\s+", " ", "g"))
            )
            for amenity in dict.fromkeys(self.amenity):
                criteria.append(
                    select(1)
                    .select_from(declared)
                    .where(normalized.in_(AMENITY_ALIASES[amenity]))
                    .correlate(Listing)
                    .exists()
                )
        return criteria
