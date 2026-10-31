"""Public-grid viewport predicates; never filter on precise owner positions."""

from typing import Any, Self

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Numeric, Text, cast, func, or_

from app.models import Listing

MAP_LIMIT = 50


def public_coordinates() -> tuple[Any, Any]:
    # Cast through PostgreSQL's shortest round-trip float text, then decimal.
    # Both filtering and returned positions use these exact expressions.
    return tuple(  # type: ignore[return-value]
        func.round(cast(cast(column, Text), Numeric), 2)
        for column in (Listing.latitude, Listing.longitude)
    )


class Viewport(BaseModel):
    west: float = Field(ge=-180, le=180, allow_inf_nan=False)
    south: float = Field(ge=-90, le=90, allow_inf_nan=False)
    east: float = Field(ge=-180, le=180, allow_inf_nan=False)
    north: float = Field(ge=-90, le=90, allow_inf_nan=False)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.south >= self.north or self.west == self.east:
            raise ValueError("Supply a nonempty viewport with south below north.")
        return self

    def predicates(self) -> list[Any]:
        latitude, longitude = public_coordinates()
        horizontal = (
            longitude.between(self.west, self.east)
            if self.west < self.east
            else or_(longitude >= self.west, longitude <= self.east)
        )
        return [latitude.between(self.south, self.north), horizontal]
