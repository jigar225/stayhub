"""Location privacy projection and persisted provider request reservation."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import location_provider
from app.auth_service import AccessContext, current_user
from app.config import get_settings
from app.discovery_map import public_coordinates
from app.errors import ApiError
from app.models import Listing, LocationProviderBudget, now
from app.security import limiter


def limited(retry: int) -> ApiError:
    return ApiError(
        429,
        "location_rate_limited",
        "Address suggestions are busy. Wait before searching again, or enter a pin manually.",
        {"Retry-After": str(max(1, retry))},
    )


def autocomplete(
    db: Session, actor: AccessContext, query: str
) -> list[location_provider.Suggestion]:
    settings = get_settings()
    with db.begin():
        user = current_user(db, actor, "host")
        limiter.check(f"location:{user.id}")
        if not settings.geoapify_api_key.get_secret_value():
            raise location_provider.unavailable()
        # Lock one persisted row across all processes; commit reservation BEFORE
        # network I/O, so even provider failures consume the conservative budget.
        budget = db.scalar(
            select(LocationProviderBudget)
            .where(LocationProviderBudget.id == 1)
            .with_for_update()
        )
        if budget is None:
            raise location_provider.unavailable()
        current = now()  # UTC/auth clock, never simulated business time.
        if budget.blocked_until is not None and budget.blocked_until > current:
            raise limited(int((budget.blocked_until - current).total_seconds()) + 1)
        if budget.day != current.date():
            budget.day, budget.requests = current.date(), 0
        recent = [
            stamp for stamp in budget.recent_requests if current.timestamp() - stamp < 1
        ]
        if budget.requests >= settings.geoapify_daily_budget:
            tomorrow = (current + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            raise limited(int((tomorrow - current).total_seconds()))
        host_requests = {
            host: [stamp for stamp in stamps if current.timestamp() - stamp < 60]
            for host, stamps in budget.host_requests.items()
            if any(current.timestamp() - stamp < 60 for stamp in stamps)
        }
        host_recent = host_requests.get(str(user.id), [])
        if len(host_recent) >= 10:
            raise limited(60)
        if len(recent) >= 4:
            raise limited(1)
        host_requests[str(user.id)] = [*host_recent, current.timestamp()]
        budget.host_requests = host_requests
        budget.requests += 1
        budget.recent_requests = [*recent, current.timestamp()]
    try:
        return location_provider.fetch_suggestions(
            query, settings.geoapify_api_key.get_secret_value()
        )
    except ApiError as error:
        # Persist cooldown after quota or transient errors; no retry storm from
        # another browser/API process. Never persist address, URL or key.
        with db.begin():
            budget = db.scalar(
                select(LocationProviderBudget)
                .where(LocationProviderBudget.id == 1)
                .with_for_update()
            )
            if budget is not None:
                until = now() + timedelta(seconds=60)
                if budget.blocked_until is None or budget.blocked_until < until:
                    budget.blocked_until = until
        raise error


def public_location(db: Session, listing_id: UUID) -> dict[str, object]:
    with db.begin():
        listing = db.scalar(
            select(Listing).where(
                Listing.id == listing_id, Listing.status == "published"
            )
        )
        if listing is None:
            raise ApiError(404, "not_found", "This listing could not be found.")
        if listing.latitude is None or listing.longitude is None:
            return {"location": None}

        latitude, longitude = db.execute(
            select(*public_coordinates()).where(Listing.id == listing_id)
        ).one()

        return {
            "location": {
                "latitude": float(latitude),
                "longitude": float(longitude),
                "grid_degrees": 0.01,
                "radius_meters": 800,
                "max_zoom": 12,
            }
        }
