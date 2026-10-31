"""Host timezone catalog and persisted cancellation-term presentation."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_listings import create, identity

from app.listing_schemas import ListingPatch
from app.policies import DEFINITIONS, describe


def test_host_timezone_catalog_and_existing_aliases(client: TestClient) -> None:
    headers = identity(client)
    response = client.get("/api/v1/host/timezones", headers=headers)
    assert response.status_code == 200
    zones = {zone["value"]: zone["label"] for zone in response.json()["items"]}
    assert zones["Asia/Kolkata"] == "Asia/Kolkata — Kolkata"
    assert "UTC" in zones and "US/Eastern" in zones
    assert client.get("/api/v1/host/timezones").status_code == 401
    draft = create(client, headers)
    for zone in ["US/Eastern", "UTC", "Asia/Kolkata"]:
        response = client.patch(
            f"/api/v1/host/listings/{draft['id']}",
            headers=headers,
            json={"version": draft["version"], "timezone": zone},
        )
        assert response.status_code == 200, response.text
        draft = response.json()["listing"]
        assert draft["timezone"] == zone
    assert (
        datetime(2027, 1, 15, tzinfo=ZoneInfo("US/Eastern")).utcoffset()
        != datetime(2027, 7, 15, tzinfo=ZoneInfo("US/Eastern")).utcoffset()
    )
    with pytest.raises(ValidationError):
        ListingPatch(version=1, timezone="UTC+5:30")


def test_all_policy_terms_come_from_persisted_definitions(client: TestClient) -> None:
    headers = identity(client)
    response = client.get("/api/v1/host/cancellation-policies", headers=headers)
    assert response.status_code == 200
    items = {item["name"]: item for item in response.json()["items"]}
    assert set(items) == {"Flexible", "Moderate", "Firm", "Strict"}
    for name, definition in DEFINITIONS.items():
        assert items[name]["terms"] == describe(definition)
        assert "Cleaning fees are fully refunded" in items[name]["terms"]
    assert "48 hours after booking" in items["Strict"]["terms"]
    assert "30 days" in items["Firm"]["terms"]
    assert "24 hours" in items["Flexible"]["terms"]
    assert "50% at least 5 days" in describe(
        {
            "windows": [
                {"hours_before": 120, "percent": 50},
                {"hours_before": 0, "percent": 0},
            ]
        }
    )


def test_public_policy_uses_the_saved_version_definition() -> None:
    from sqlalchemy.orm import Session
    from test_discovery import published

    from app import pricing
    from app.db import get_engine
    from app.models import CancellationPolicy, Listing

    with Session(get_engine()) as db:
        _, lid = published(db)
        with db.begin():
            version = CancellationPolicy(
                name="Moderate",
                version=2,
                definition={
                    "windows": [
                        {"hours_before": 720, "percent": 50},
                        {"hours_before": 0, "percent": 0},
                    ]
                },
            )
            db.add(version)
            db.flush()
            listing = db.get(Listing, lid)
            assert listing is not None
            listing.policy_id = version.id
            public = pricing.policy(db, listing)
            assert public.version == 2
            assert public.terms == describe(version.definition)
            assert "50% at least 30 days" in public.terms
