"""Immutable version-one definitions. Refund computation is a later milestone."""

from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CancellationPolicy

DEFINITIONS: dict[str, dict[str, object]] = {
    "Flexible": {
        "windows": [
            {"hours_before": 24, "percent": 100},
            {"hours_before": 0, "percent": 0},
        ]
    },
    "Moderate": {
        "windows": [
            {"hours_before": 120, "percent": 100},
            {"hours_before": 24, "percent": 50},
            {"hours_before": 0, "percent": 0},
        ]
    },
    "Firm": {
        "windows": [
            {"hours_before": 720, "percent": 100},
            {"hours_before": 168, "percent": 50},
            {"hours_before": 0, "percent": 0},
        ]
    },
    "Strict": {
        "booking_grace_hours": 48,
        "requires_before_checkin": True,
        "grace_percent": 100,
        "windows": [
            {"hours_before": 336, "percent": 50},
            {"hours_before": 0, "percent": 0},
        ],
    },
}


def seed_policies(db: Session) -> None:
    for name, definition in DEFINITIONS.items():
        existing = db.scalar(
            select(CancellationPolicy).where(
                CancellationPolicy.name == name, CancellationPolicy.version == 1
            )
        )
        if existing is not None:
            if existing.definition != definition:
                raise ValueError(
                    "An existing cancellation policy version differs; publish a new version rather than rewriting it"
                )
            continue
        db.add(
            CancellationPolicy(
                id=uuid5(NAMESPACE_URL, f"stayhub:policy:{name}:1"),
                name=name,
                version=1,
                definition=definition,
            )
        )
