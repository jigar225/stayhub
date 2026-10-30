"""Pure booked-policy refund arithmetic, inclusive elapsed-time boundaries."""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class RefundAmounts:
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

    def values(self) -> dict[str, int]:
        return asdict(self)


def half_up(amount: int, percent: int) -> int:
    return (amount * percent + 50) // 100


def calculate(
    definition: dict[str, Any],
    created_at: datetime,
    check_in: datetime,
    now: datetime,
    nights: int,
    cleaning: int,
    guest_fee: int,
    *,
    full: bool = False,
) -> RefundAmounts:
    if not full and now >= check_in:
        raise ValueError("Cancellation is only available before scheduled check-in.")
    percent = 100 if full else 0
    if not full:
        grace = definition.get("booking_grace_hours")
        if grace is not None and now - created_at <= timedelta(hours=grace):
            percent = int(definition["grace_percent"])
        else:
            for window in sorted(
                definition["windows"], key=lambda x: x["hours_before"], reverse=True
            ):
                if check_in - now >= timedelta(hours=window["hours_before"]):
                    percent = int(window["percent"])
                    break
    nr, fr = half_up(nights, percent), half_up(guest_fee, percent)
    retained, retained_fee = nights - nr, guest_fee - fr
    fee = half_up(retained, 3)
    return RefundAmounts(
        percent,
        nr,
        cleaning,
        fr,
        nr + cleaning + fr,
        retained,
        retained_fee,
        fee,
        retained - fee,
        retained_fee + fee,
    )
