"""M9A API contracts. Fake Geoapify boundary only; no external credits used."""

from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session
from test_discovery import published
from test_listings import create, identity

from app import listing_service, location_provider
from app.config import get_settings
from app.db import get_engine
from app.errors import ApiError
from app.listing_schemas import ListingPatch
from app.models import LocationProviderBudget, now

SEARCH = "/api/v1/host/location/autocomplete"


@pytest.fixture(autouse=True)
def reset_budget() -> None:
    with get_engine().begin() as connection:
        connection.execute(
            text(
                "UPDATE location_provider_budget SET day = CURRENT_DATE, requests = 0, recent_requests = '[]', host_requests = '{}', blocked_until = NULL WHERE id = 1"
            )
        )


@pytest.mark.parametrize(
    "coordinates",
    [
        {"latitude": 38.7},
        {"longitude": -9.1},
        {"latitude": 38.7, "longitude": None},
        {"latitude": 91, "longitude": 0},
        {"latitude": 0, "longitude": -181},
        {"latitude": float("nan"), "longitude": 0},
        {"latitude": 0, "longitude": float("inf")},
        {"latitude": True, "longitude": 0},
        {"latitude": "38.7", "longitude": 0},
    ],
)
def test_coordinate_validation(coordinates: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ListingPatch(version=1, **coordinates)


def test_owner_save_reload_clear_invalidation_conflict_and_denials(
    client: TestClient,
) -> None:
    owner, other, guest = (
        identity(client),
        identity(client),
        identity(client, host=False),
    )
    listing = create(client, owner)
    path = f"/api/v1/host/listings/{listing['id']}"
    body = {
        "version": 1,
        "address": "10 Test Street, Unit 4",
        "latitude": 38.723456,
        "longitude": -9.134567,
    }
    for headers, expected in [({}, 401), (guest, 403), (other, 404)]:
        assert client.patch(path, headers=headers, json=body).status_code == expected
    saved = client.patch(path, headers=owner, json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["listing"]["latitude"] == 38.723456
    assert client.get(path, headers=owner).json() == saved.json()
    assert client.patch(path, headers=owner, json=body).status_code == 409
    edited = client.patch(
        path, headers=owner, json={"version": 2, "address": "11 Test Street"}
    ).json()["listing"]
    assert edited["latitude"] is None and edited["longitude"] is None
    # Explicit coordinates reconfirm edited address, without timezone inference.
    reconfirmed = client.patch(
        path, headers=owner, json={"version": 3, "latitude": 0, "longitude": 0}
    ).json()["listing"]
    assert reconfirmed["latitude"] == 0 and reconfirmed["timezone"] is None
    cleared = client.patch(
        path, headers=owner, json={"version": 4, "latitude": None, "longitude": None}
    )
    assert cleared.status_code == 200 and cleared.json()["listing"]["latitude"] is None
    invalid_fields: list[dict[str, Any]] = [
        {"latitude": 1},
        {"latitude": None, "longitude": 2},
        {"latitude": 0, "longitude": 181},
    ]
    for fields in invalid_fields:
        assert (
            client.patch(path, headers=owner, json={"version": 5, **fields}).status_code
            == 422
        )


def test_public_coarse_only_null_publication_and_unlisted(client: TestClient) -> None:
    with Session(get_engine()) as db:
        actor, listing_id = published(db)
        listing = listing_service.get_listing(db, actor, listing_id).listing
        path = f"/api/v1/listings/{listing_id}/location"
        assert client.get(path).json() == {"location": None}
        # Published listings remain publishable without any location.
        listing = listing_service.update_listing(
            db,
            actor,
            listing_id,
            ListingPatch(
                version=listing.version, latitude=38.723456, longitude=-9.134567
            ),
        ).listing
        result = client.get(path)
        assert (
            result.status_code == 200 and result.headers["cache-control"] == "no-store"
        )
        location = result.json()["location"]
        assert location == {
            "latitude": 38.72,
            "longitude": -9.13,
            "grid_degrees": 0.01,
            "radius_meters": 800,
            "max_zoom": 12,
        }
        public_detail = client.get(f"/api/v1/listings/{listing_id}").text
        public_search = client.get("/api/v1/listings").text
        for payload in [result.text, public_detail, public_search]:
            assert "38.723456" not in payload and "-9.134567" not in payload
            assert "Private exact street" not in payload
        listing_service.unlist(db, actor, listing_id, listing.version)
        assert client.get(path).status_code == 404


def configure_key(monkeypatch: Any) -> None:
    monkeypatch.setenv("GEOAPIFY_API_KEY", "fake-private-test-key")
    get_settings.cache_clear()


def test_search_auth_validation_missing_key_and_mock_success(
    client: TestClient, monkeypatch: Any
) -> None:
    owner, guest = identity(client), identity(client, host=False)
    assert client.post(SEARCH, json={"query": "Lisbon"}).status_code == 401
    assert (
        client.post(SEARCH, headers=guest, json={"query": "Lisbon"}).status_code == 403
    )
    for query in ["ab", "   ", "x" * 201]:
        assert (
            client.post(SEARCH, headers=owner, json={"query": query}).status_code == 422
        )
    assert (
        client.post(
            SEARCH,
            headers={**owner, "Origin": "https://evil.example"},
            json={"query": "Lisbon"},
        ).status_code
        == 403
    )
    monkeypatch.setenv("GEOAPIFY_API_KEY", "")
    get_settings.cache_clear()
    assert (
        client.post(SEARCH, headers=owner, json={"query": "Lisbon"}).status_code == 503
    )
    configure_key(monkeypatch)
    calls: list[str] = []

    def fake(query: str, key: str) -> list[location_provider.Suggestion]:
        assert key == "fake-private-test-key"
        calls.append(query)
        return [
            location_provider.Suggestion(
                display_address="Lisbon test", latitude=38.7, longitude=-9.1
            )
        ]

    monkeypatch.setattr(location_provider, "fetch_suggestions", fake)
    response = client.post(SEARCH, headers=owner, json={"query": " Lisbon "})
    assert response.status_code == 200 and calls == ["Lisbon"]
    assert response.json()["items"][0]["display_address"] == "Lisbon test"
    assert "fake-private-test-key" not in response.text


def test_global_rate_daily_budget_failures_and_cooldown(
    client: TestClient, monkeypatch: Any
) -> None:
    owner = identity(client)
    configure_key(monkeypatch)
    calls: list[str] = []

    def fake(query: str, key: str) -> list[location_provider.Suggestion]:
        calls.append(query)
        return []

    monkeypatch.setattr(location_provider, "fetch_suggestions", fake)
    with Session(get_engine()) as db, db.begin():
        budget = db.get(LocationProviderBudget, 1)
        assert budget
        budget.recent_requests = [now().timestamp()] * 4
    response = client.post(SEARCH, headers=owner, json={"query": "Lisbon"})
    assert response.status_code == 429 and calls == []
    with Session(get_engine()) as db, db.begin():
        budget = db.get(LocationProviderBudget, 1)
        assert budget
        budget.recent_requests, budget.requests = (
            [],
            get_settings().geoapify_daily_budget,
        )
    assert (
        client.post(SEARCH, headers=owner, json={"query": "Lisbon"}).status_code == 429
    )
    assert calls == []
    with Session(get_engine()) as db, db.begin():
        budget = db.get(LocationProviderBudget, 1)
        assert budget
        budget.requests = 0

    def fail(query: str, key: str) -> list[location_provider.Suggestion]:
        calls.append(query)
        raise ApiError(
            429,
            "location_rate_limited",
            "Temporarily unavailable",
            {"Retry-After": "60"},
        )

    monkeypatch.setattr(location_provider, "fetch_suggestions", fail)
    assert (
        client.post(SEARCH, headers=owner, json={"query": "Lisbon"}).status_code == 429
    )
    assert (
        client.post(SEARCH, headers=owner, json={"query": "Lisbon"}).status_code == 429
    )
    assert len(calls) == 1
    with Session(get_engine()) as db, db.begin():
        budget = db.get(LocationProviderBudget, 1)
        assert budget and budget.requests == 1
        budget.blocked_until = now() - timedelta(seconds=1)
    monkeypatch.setattr(location_provider, "fetch_suggestions", fake)
    assert (
        client.post(SEARCH, headers=owner, json={"query": "Lisbon"}).status_code == 200
    )


def test_per_host_limit_without_provider_requests(
    client: TestClient, monkeypatch: Any
) -> None:
    owner = identity(client)
    monkeypatch.setenv("GEOAPIFY_API_KEY", "")
    get_settings.cache_clear()
    for _ in range(get_settings().rate_limit_attempts):
        assert (
            client.post(SEARCH, headers=owner, json={"query": "Lisbon"}).status_code
            == 503
        )
    assert (
        client.post(SEARCH, headers=owner, json={"query": "Lisbon"}).status_code == 429
    )


def test_additive_migration_preserves_existing_listing_and_photos(
    client: TestClient,
) -> None:
    """Exercise 0006 -> 0007 over an actual published stay and private photos."""
    from alembic.config import Config

    from alembic import command

    with Session(get_engine()) as db:
        _, listing_id = published(db)
    configuration = Config("alembic.ini")
    try:
        command.downgrade(configuration, "0006_listing_categories")
        with get_engine().connect() as connection:
            before = connection.execute(
                text("SELECT to_jsonb(l) FROM listings l WHERE id = :id"),
                {"id": listing_id},
            ).scalar_one()
            photos_before = connection.execute(
                text(
                    "SELECT jsonb_agg(to_jsonb(p) ORDER BY id) FROM listing_photos p WHERE listing_id = :id"
                ),
                {"id": listing_id},
            ).scalar_one()
        command.upgrade(configuration, "head")
        with get_engine().connect() as connection:
            after = connection.execute(
                text(
                    "SELECT to_jsonb(l) - 'latitude' - 'longitude' FROM listings l WHERE id = :id"
                ),
                {"id": listing_id},
            ).scalar_one()
            photos_after = connection.execute(
                text(
                    "SELECT jsonb_agg(to_jsonb(p) ORDER BY id) FROM listing_photos p WHERE listing_id = :id"
                ),
                {"id": listing_id},
            ).scalar_one()
            assert connection.execute(
                text(
                    "SELECT latitude IS NULL AND longitude IS NULL FROM listings WHERE id = :id"
                ),
                {"id": listing_id},
            ).scalar_one()
        assert before == after and photos_before == photos_after
    finally:
        command.upgrade(configuration, "head")


@pytest.mark.parametrize(
    "mode", ["timeout", "quota", "oversize", "malformed", "bad_coordinate", "redirect"]
)
def test_provider_boundary_failure_redacts_details(monkeypatch: Any, mode: str) -> None:
    import io
    import json
    import urllib.error
    import urllib.request
    from email.message import Message

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: Any) -> None:
            pass

        def read(self, size: int) -> bytes:
            assert size == location_provider.MAX_BYTES + 1
            if mode == "oversize":
                return b"x" * size
            if mode == "malformed":
                return b"secret-provider-body"
            return json.dumps(
                {"results": [{"formatted": "Test", "lat": 91, "lon": 0}]}
            ).encode()

    class Opener:
        def open(self, request: Any, timeout: int) -> Response:
            assert request.full_url.startswith(location_provider.ENDPOINT + "?")
            assert timeout == 4
            if mode == "timeout":
                raise TimeoutError("private-key-in-error")
            if mode in {"quota", "redirect"}:
                raise urllib.error.HTTPError(
                    "https://private-key",
                    429 if mode == "quota" else 302,
                    "secret-provider-body",
                    Message(),
                    io.BytesIO(b"private"),
                )
            return Response()

    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: Opener())
    with pytest.raises(ApiError) as caught:
        location_provider.fetch_suggestions("Private street", "private-key")
    assert caught.value.status == (429 if mode == "quota" else 503)
    assert (
        "private" not in caught.value.message and "secret" not in caught.value.message
    )


def test_durable_per_host_limit_across_api_processes(
    client: TestClient, monkeypatch: Any
) -> None:
    from app.models import Listing

    owner = identity(client)
    listing = create(client, owner)
    configure_key(monkeypatch)
    calls: list[str] = []

    def fake(query: str, key: str) -> list[location_provider.Suggestion]:
        calls.append(query)
        return []

    monkeypatch.setattr(location_provider, "fetch_suggestions", fake)
    with Session(get_engine()) as db, db.begin():
        saved = db.get(Listing, UUID(listing["id"]))
        budget = db.get(LocationProviderBudget, 1)
        assert saved and budget
        budget.host_requests = {str(saved.owner_id): [now().timestamp()] * 10}
    assert (
        client.post(SEARCH, headers=owner, json={"query": "Lisbon"}).status_code == 429
    )
    assert calls == []


def test_provider_boundary_normalizes_and_bounds_results(monkeypatch: Any) -> None:
    import json
    import urllib.request

    results: list[dict[str, object]] = [
        {
            "formatted": " Test street ",
            "lat": 38.7,
            "lon": -9.1,
            "private_provider_data": "discard",
        }
    ]

    class Response:
        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: Any) -> None:
            pass

        def read(self, size: int) -> bytes:
            return json.dumps({"results": results}).encode()

    class Opener:
        def open(self, request: Any, timeout: int) -> Response:
            return Response()

    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: Opener())
    suggestions = location_provider.fetch_suggestions("Test", "fake-key")
    assert suggestions[0].model_dump() == {
        "display_address": "Test street",
        "latitude": 38.7,
        "longitude": -9.1,
    }
    results *= 6
    with pytest.raises(ApiError):
        location_provider.fetch_suggestions("Test", "fake-key")
