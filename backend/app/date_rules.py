"""Bounded listing-local date rules and explicit DST resolution."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app import business_time
from app.errors import ApiError


def invalid_date(message: str, field: str = "check_in") -> ApiError:
    return ApiError(422, "validation_error", message, field_errors={field: message})


def local_today(timezone: str, as_of: datetime | None = None) -> date:
    return (as_of or business_time.now()).astimezone(ZoneInfo(timezone)).date()


def stay_range(
    check_in: date,
    check_out: date,
    timezone: str | None = None,
    *,
    as_of: datetime | None = None,
) -> None:
    nights = (check_out - check_in).days
    if not 1 <= nights <= 180:
        raise invalid_date(
            "Choose a stay of 1–180 nights with checkout after check-in.", "check_out"
        )
    if timezone is not None:
        today = local_today(timezone, as_of)
        if check_in < today:
            raise invalid_date("Check-in cannot be in the listing's local past.")
        if check_in > today + timedelta(days=730):
            raise invalid_date("Check-in must be within 730 days.")


def read_range(start: date, end: date, timezone: str) -> None:
    today = local_today(timezone)
    if not 1 <= (end - start).days <= 93:
        raise invalid_date("Choose a calendar range of 1–93 days.", "end")
    if start < today - timedelta(days=31) or end > today + timedelta(days=730):
        raise invalid_date(
            "Calendar range must be within the previous 31 and next 730 days.", "start"
        )


def scheduled(day: date, clock: str, timezone: str) -> datetime:
    naive = datetime.combine(day, time.fromisoformat(clock))
    localized = naive.replace(tzinfo=ZoneInfo(timezone), fold=0)
    utc = localized.astimezone(UTC)
    if utc.astimezone(ZoneInfo(timezone)).replace(tzinfo=None) != naive:
        raise invalid_date(
            "The scheduled local time does not exist because of daylight saving. Choose another date."
        )
    return utc
