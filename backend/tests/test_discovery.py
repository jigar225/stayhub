"""M3 real PostgreSQL/S3 calendar, public projection, quote and import regressions."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from test_listings import image_bytes
from test_services import account

from app import (
    auth_service,
    business_time,
    calendar_service,
    discovery_service,
    listing_service,
    storage,
)
from app.auth_service import AccessContext
from app.config import get_settings
from app.db import get_engine
from app.discovery_schemas import QuoteInput, StayDates
from app.errors import ApiError
from app.listing_schemas import ListingPatch, UploadIntentInput
from app.models import (
    AuthSession,
    CalendarEntry,
    DemoAssetPhoto,
    DemoImport,
    ListingPhoto,
    User,
)
from app.provision_users import _stable, provision
from app.schemas import LoginInput

BUSINESS_NOW = datetime(2027, 1, 15, 12, tzinfo=UTC)
START = date(2027, 2, 1)
END = date(2027, 2, 6)


@pytest.fixture(autouse=True)
def fixed_business_time(monkeypatch: Any) -> None:
    monkeypatch.setattr(business_time, "now", lambda: BUSINESS_NOW)


def _provisioned_actor(email: str) -> AccessContext:
    with Session(get_engine()) as db:
        user = db.scalar(select(User).where(User.email == email))
        assert user is not None
        session = db.scalar(select(AuthSession).where(AuthSession.user_id == user.id))
        assert session is not None
        return AccessContext(
            user_id=user.id, session_id=session.id, expires_at=session.expires_at
        )


def published(
    db: Session,
    *,
    destination: str = "Lisbon",
    timezone: str = "Europe/Lisbon",
    booking_mode: str = "instant",
    nightly: int = 12800,
    cleaning: int = 3500,
) -> tuple[auth_service.AccessContext, UUID]:
    actor, _ = account(db, host=True)
    listing = listing_service.create_listing(db, actor).listing
    policy = listing_service.policies(db, actor).items[0]
    fields = {
        "property_type": "apartment",
        "address": "Private exact street 123",
        "destination": destination,
        "timezone": timezone,
        "capacity": 2,
        "bedrooms": 1,
        "beds": 1,
        "baths": 1,
        "title": "A test stay",
        "description": "A bright test apartment.",
        "amenities": ["Kitchen"],
        "house_rules": ["No smoking"],
        "nightly_minor": nightly,
        "cleaning_minor": cleaning,
        "policy_id": policy.id,
        "booking_mode": booking_mode,
    }
    listing = listing_service.update_listing(
        db, actor, listing.id, ListingPatch(version=listing.version, **fields)
    ).listing
    content = image_bytes()
    for _ in range(5):
        intent = listing_service.create_upload_intent(
            db,
            actor,
            listing.id,
            UploadIntentInput(content_type="image/png", bytes=len(content)),
        )
        with db.begin():
            photo = db.get(ListingPhoto, intent.photo_id)
            assert photo
            key = photo.staging_key
        storage.s3_client().put_object(
            Bucket=get_settings().s3_bucket,
            Key=key,
            Body=content,
            ContentType="image/png",
        )
        listing = listing_service.complete_photo(
            db, actor, listing.id, intent.photo_id
        ).listing
    listing_service.publish(db, actor, listing.id, listing.version)
    return actor, listing.id


def test_calendar_blocks_adjacent_overlap_unblock_owner_and_no_content_version(
    client: TestClient,
) -> None:
    with Session(get_engine()) as db:
        actor, listing_id = published(db)
        before = listing_service.get_listing(db, actor, listing_id).listing
        block = calendar_service.create_block(
            db, actor, listing_id, StayDates(check_in=START, check_out=END)
        ).block
        calendar_service.create_block(
            db,
            actor,
            listing_id,
            StayDates(check_in=END, check_out=END + timedelta(days=1)),
        )
        with pytest.raises(ApiError) as conflict:
            calendar_service.create_block(
                db,
                actor,
                listing_id,
                StayDates(check_in=START + timedelta(days=1), check_out=END),
            )
        assert (
            conflict.value.code == "availability_conflict"
            and conflict.value.status == 409
        )
        result = calendar_service.calendar(
            db, actor, listing_id, START, END + timedelta(days=2)
        )
        assert len(result.items) == 2
        calendar_service.remove_block(db, actor, listing_id, block.id)
        calendar_service.remove_block(db, actor, listing_id, block.id)
        assert listing_service.get_listing(db, actor, listing_id).listing == before
        other, issue = account(db, host=True)
        response = client.get(
            f"/api/v1/host/listings/{listing_id}/calendar?start={START}&end={END}",
            headers={"Authorization": f"Bearer {issue.body.access_token}"},
        )
        assert response.status_code == 404
        guest, guest_issue = account(db)
        assert (
            client.post(
                f"/api/v1/host/listings/{listing_id}/blocks",
                headers={"Authorization": f"Bearer {guest_issue.body.access_token}"},
                json={"check_in": str(START), "check_out": str(END)},
            ).status_code
            == 403
        )
        with db.begin():
            stored = db.get(CalendarEntry, block.id)
            assert stored and not stored.active


def test_postgres_exclusion_cannot_be_bypassed_by_concurrent_writes() -> None:
    with Session(get_engine()) as db:
        _, listing_id = published(db)

    def insert() -> str:
        try:
            with Session(get_engine()) as connection, connection.begin():
                connection.add(
                    CalendarEntry(
                        listing_id=listing_id,
                        kind="block",
                        check_in=START,
                        check_out=END,
                    )
                )
            return "committed"
        except (IntegrityError, OperationalError) as error:
            # Concurrent exclusion-index insertion can abort either with an
            # exclusion violation or as a narrowly identified deadlock victim.
            # Neither transaction may bypass the constraint and both commit.
            assert getattr(error.orig, "sqlstate", None) in {"23P01", "40P01"}
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: insert(), range(2))) == [
            "committed",
            "conflict",
        ]
    with Session(get_engine()) as db, db.begin():
        assert db.scalar(select(func.count()).select_from(CalendarEntry)) == 1
        with pytest.raises(IntegrityError):
            # Kind/reference consistency belongs to the same future occupancy table.
            with db.begin_nested():
                db.add(
                    CalendarEntry(
                        listing_id=listing_id,
                        kind="reservation",
                        reservation_id=None,
                        check_in=END,
                        check_out=END + timedelta(days=1),
                    )
                )
                db.flush()


def test_block_api_race_and_date_guards(client: TestClient) -> None:
    with Session(get_engine()) as db:
        actor, listing_id = published(db)
        issue = auth_service.login(
            db,
            LoginInput(
                email=auth_service.profile(db, actor).user.email,
                password="service-test-password!",
            ),
        )
    headers = {
        "Authorization": f"Bearer {issue.body.access_token}",
        "Origin": "http://localhost:5173",
    }

    def block() -> int:
        with TestClient(
            client.app, base_url="http://localhost:5173", headers=headers
        ) as parallel:
            return int(
                parallel.post(
                    f"/api/v1/host/listings/{listing_id}/blocks",
                    json={"check_in": str(START), "check_out": str(END)},
                ).status_code
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: block(), range(2))) == [201, 409]
    for start, end in [
        (START, START),
        (END, START),
        (START, START + timedelta(days=181)),
        (BUSINESS_NOW.date() - timedelta(days=1), START),
        (
            BUSINESS_NOW.date() + timedelta(days=731),
            BUSINESS_NOW.date() + timedelta(days=732),
        ),
    ]:
        assert (
            client.post(
                f"/api/v1/host/listings/{listing_id}/blocks",
                headers=headers,
                json={"check_in": str(start), "check_out": str(end)},
            ).status_code
            == 422
        )
    assert (
        client.get(
            f"/api/v1/host/listings/{listing_id}/calendar?start={START}&end={START + timedelta(days=94)}",
            headers=headers,
        ).status_code
        == 422
    )


def test_public_browse_search_full_range_visibility_privacy_and_batch_reads(
    client: TestClient,
) -> None:
    with Session(get_engine()) as db:
        actor, listing_id = published(db)
        other_actor, other_id = published(
            db, destination="Kyoto", timezone="Asia/Tokyo"
        )
        draft = listing_service.create_listing(db, actor).listing
        calendar_service.create_block(
            db,
            actor,
            listing_id,
            StayDates(
                check_in=START + timedelta(days=2), check_out=START + timedelta(days=3)
            ),
        )
    result = client.get("/api/v1/listings?destination=lIsB&guests=2").json()
    assert [row["id"] for row in result["items"]] == [str(listing_id)]
    summary = result["items"][0]
    assert summary["stay_price"] is None and len(summary["photos"]) == 1
    assert (
        client.get(
            f"/api/v1/listings?destination=Lisbon&check_in={START}&check_out={END}&guests=2"
        ).json()["items"]
        == []
    )
    assert client.get(
        f"/api/v1/listings?destination=Lisbon&check_in={START}&check_out={START + timedelta(days=2)}&guests=2"
    ).json()["items"][0]["id"] == str(listing_id)
    assert client.get("/api/v1/listings?destination=%25").json()["items"] == []
    assert client.get("/api/v1/listings?guests=3").json()["items"] == []
    detail = client.get(f"/api/v1/listings/{listing_id}").json()["listing"]
    assert len(detail["photos"]) == 5 and detail["host_name"] == "Service user"
    assert "hours" in detail["policy"]["terms"] or "days" in detail["policy"]["terms"]
    forbidden = {
        "address",
        "email",
        "owner_id",
        "status",
        "created_at",
        "updated_at",
        "version",
        "staging_key",
        "final_key",
    }
    assert not (forbidden & set(summary)) and not (forbidden & set(detail))
    assert "Private exact street" not in json.dumps(detail)
    image = httpx.get(detail["photos"][0]["url"])
    assert image.status_code == 200
    assert httpx.get(detail["photos"][0]["url"].split("?")[0]).status_code == 403
    assert len(client.get(f"/api/v1/listings/{listing_id}/photos").json()["items"]) == 5
    unavailable = client.get(
        f"/api/v1/listings/{listing_id}/availability?start={START}&end={END}"
    ).json()["unavailable"]
    assert set(unavailable[0]) == {"check_in", "check_out"}
    for suffix in ["", "/photos", f"/availability?start={START}&end={END}"]:
        assert client.get(f"/api/v1/listings/{draft.id}{suffix}").status_code == 404
    with Session(get_engine()) as db:
        saved = listing_service.get_listing(db, other_actor, other_id).listing
        listing_service.unlist(db, other_actor, other_id, saved.version)
    assert client.get(f"/api/v1/listings/{other_id}").status_code == 404
    assert client.get(f"/api/v1/listings/{other_id}/photos").status_code == 404


def test_public_pagination_and_invalid_search_parameters(client: TestClient) -> None:
    with Session(get_engine()) as db:
        _, first = published(db)
        _, second = published(db)
    page = client.get("/api/v1/listings?limit=1").json()
    next_page = client.get(
        f"/api/v1/listings?limit=1&cursor={page['next_cursor']}"
    ).json()
    assert {page["items"][0]["id"], next_page["items"][0]["id"]} == {
        str(first),
        str(second),
    }
    for query in [
        f"check_in={START}",
        f"check_out={END}",
        f"check_in={END}&check_out={START}",
        "guests=0",
        "limit=101",
        "cursor=bad",
        "check_in=bad&check_out=bad",
        "check_in=2026-01-01&check_out=2026-01-02",
        "destination=missing&check_in=2026-01-01&check_out=2026-01-02",
    ]:
        assert client.get(f"/api/v1/listings?{query}").status_code == 422


def test_quote_arithmetic_signing_binding_availability_and_auth_separation(
    client: TestClient,
) -> None:
    with Session(get_engine()) as db:
        actor, listing_id = published(db)
    response = client.post(
        "/api/v1/booking-quotes",
        json={
            "listing_id": str(listing_id),
            "check_in": str(START),
            "check_out": str(END),
            "guests": 2,
        },
    )
    assert response.status_code == 200, response.text
    quote = response.json()["quote"]
    assert [
        quote[key]
        for key in [
            "nights",
            "nights_minor",
            "subtotal_minor",
            "guest_fee_minor",
            "total_minor",
        ]
    ] == [5, 64000, 67500, 9450, 76950]
    priced = client.get(
        f"/api/v1/listings?check_in={START}&check_out={END}&guests=2"
    ).json()["items"][0]["stay_price"]
    assert all(priced[key] == quote[key] for key in priced)
    claims = jwt.decode(
        quote["quote_token"],
        get_settings().jwt_secret.get_secret_value(),
        algorithms=["HS256"],
        audience="stayhub-booking-quote",
        issuer=get_settings().jwt_issuer,
        options={"verify_iat": False},
    )
    assert claims["purpose"] == "booking_quote" and claims["listing_id"] == str(
        listing_id
    )
    assert claims["listing_version"] > 1 and claims["guests"] == 2
    assert claims["exp"] - claims["iat"] == 600
    assert (
        client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {quote['quote_token']}"},
        ).status_code
        == 401
    )
    with Session(get_engine()) as db:
        calendar_service.create_block(
            db, actor, listing_id, StayDates(check_in=START, check_out=END)
        )
    assert (
        client.post(
            "/api/v1/booking-quotes",
            json={
                "listing_id": str(listing_id),
                "check_in": str(START),
                "check_out": str(END),
                "guests": 2,
            },
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/v1/booking-quotes",
            json={
                "listing_id": str(listing_id),
                "check_in": str(START),
                "check_out": str(END),
                "guests": 3,
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/booking-quotes",
            json={
                "listing_id": str(listing_id),
                "check_in": str(START),
                "check_out": str(END),
                "guests": 2,
                "total_minor": 1,
            },
        ).status_code
        == 422
    )


def test_half_up_dst_nights_nonexistent_and_ambiguous_local_times(
    monkeypatch: Any,
) -> None:
    from app.date_rules import scheduled

    with Session(get_engine()) as db:
        actor, listing_id = published(db, nightly=125, cleaning=0)
        saved = listing_service.get_listing(db, actor, listing_id).listing
        listing_service.update_listing(
            db,
            actor,
            listing_id,
            ListingPatch(version=saved.version, check_out_time="15:00"),
        )
        quote = discovery_service.quote(
            db,
            QuoteInput(
                listing_id=listing_id,
                check_in=date(2027, 3, 27),
                check_out=date(2027, 3, 30),
                guests=1,
            ),
        ).quote
        assert (
            quote.nights == 3
            and quote.nights_minor == 375
            and quote.guest_fee_minor == 53
        )
        assert (
            quote.scheduled_check_out - quote.scheduled_check_in
        ).total_seconds() == 3 * 86400 - 3600
    with pytest.raises(ApiError):
        scheduled(date(2027, 3, 28), "01:30", "Europe/Lisbon")
    assert scheduled(date(2027, 10, 31), "01:30", "Europe/Lisbon") == datetime(
        2027, 10, 31, 0, 30, tzinfo=UTC
    )


def test_request_lead_time_and_listing_local_past_not_auth_clock(
    client: TestClient, monkeypatch: Any
) -> None:
    monkeypatch.setattr(
        business_time, "now", lambda: datetime(2027, 1, 15, 23, 30, tzinfo=UTC)
    )
    with Session(get_engine()) as db:
        actor, listing_id = published(
            db, destination="Kyoto", timezone="Asia/Tokyo", booking_mode="request"
        )
        body = QuoteInput(
            listing_id=listing_id,
            check_in=date(2027, 1, 16),
            check_out=date(2027, 1, 17),
            guests=1,
        )
        with pytest.raises(ApiError) as lead:
            discovery_service.quote(db, body)
        assert "24 hours" in lead.value.message
        assert (
            discovery_service.browse(db, "Kyoto", body.check_in, body.check_out).items
            == []
        )
        with pytest.raises(ApiError):
            discovery_service.quote(
                db, body.model_copy(update={"check_in": date(2027, 1, 15)})
            )
        assert auth_service.profile(db, actor).user.id == actor.user_id


def test_provision_rerun_preserves_host_edits(tmp_path: Path) -> None:
    content = image_bytes()
    assets = []
    for index in range(5):
        name = f"photo-{index}.png"
        (tmp_path / name).write_bytes(content)
        assets.append(
            {
                "id": f"photo-{index}",
                "file": name,
                "source_page": "https://example.com/license",
                "image_url": "https://example.com/test.png",
                "creator": "Isolated test fixture",
                "license": "test-only",
                "license_url": "https://example.com/license",
                "attribution": "Generated fixture for automated test, not demo content",
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
            }
        )
    specification = {
        "demo_key": "isolated-seed-v1",
        "title": "Fictional test demo",
        "destination": "Lisbon",
        "timezone": "Europe/Lisbon",
        "property_type": "apartment",
        "address": "Fictional test address",
        "capacity": 2,
        "bedrooms": 1,
        "beds": 1,
        "baths": 1,
        "description": "Fictional fixture",
        "amenities": [],
        "house_rules": [],
        "nightly_minor": 12800,
        "cleaning_minor": 3500,
        "policy_name": "Moderate",
        "booking_mode": "instant",
        "check_in_time": "15:00",
        "check_out_time": "11:00",
        "asset_ids": [asset["id"] for asset in assets],
    }
    user = {
        "key": "isolated-host",
        "name": "Isolated Host",
        "email": "isolated-host@example.com",
        "roles": ["guest", "host"],
        "listings": [specification],
    }
    path = tmp_path / "provision.json"
    path.write_text(
        json.dumps({"schema_version": 1, "assets": assets, "users": [user]})
    )
    credentials = tmp_path / "creds.txt"
    with Session(get_engine()) as db:
        first = provision(db, path, credentials)
        assert first[0]["status"] == "imported"
    listing_id = _stable("listing", "isolated-seed-v1")
    actor = _provisioned_actor("isolated-host@example.com")
    with Session(get_engine()) as db:
        saved = listing_service.get_listing(db, actor, listing_id).listing
        assert saved.status == "published"
        changed = listing_service.update_listing(
            db,
            actor,
            listing_id,
            ListingPatch(version=saved.version, title="Host edited title"),
        ).listing
        changed = listing_service.unlist(db, actor, listing_id, changed.version).listing
    with Session(get_engine()) as db:
        third = provision(db, path, credentials)
        assert third[0]["status"] == "preserved"
    with Session(get_engine()) as db:
        assert listing_service.get_listing(db, actor, listing_id).listing == changed
        assert db.scalar(select(func.count()).select_from(DemoImport)) == 1
        assert db.scalar(select(func.count()).select_from(DemoAssetPhoto)) == 5


def test_search_future_horizon_uses_matching_listing_local_date(
    client: TestClient, monkeypatch: Any
) -> None:
    monkeypatch.setattr(
        business_time, "now", lambda: datetime(2027, 1, 15, 23, 30, tzinfo=UTC)
    )
    with Session(get_engine()) as db:
        _, listing_id = published(db, destination="Kyoto", timezone="Asia/Tokyo")
    # Tokyo is already Jan16 while UTC is Jan15: its local +730 date remains
    # valid even though it is731 calendar days from the UTC date.
    valid = date(2027, 1, 16) + timedelta(days=730)
    response = client.get(
        f"/api/v1/listings?destination=Kyoto&check_in={valid}&check_out={valid + timedelta(days=1)}"
    )
    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == str(listing_id)
    too_far = valid + timedelta(days=1)
    response = client.get(
        f"/api/v1/listings?destination=Kyoto&check_in={too_far}&check_out={too_far + timedelta(days=1)}"
    )
    assert response.status_code == 422
    # With no destination/capacity candidates, use the documented UTC fallback.
    fallback_too_far = date(2027, 1, 15) + timedelta(days=731)
    assert (
        client.get(
            f"/api/v1/listings?destination=missing&check_in={fallback_too_far}&check_out={fallback_too_far + timedelta(days=1)}"
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    ("mode", "timezone", "now", "allowed"),
    [
        ("instant", "Asia/Kolkata", "2027-01-15T09:29:59+00:00", True),
        ("instant", "Asia/Kolkata", "2027-01-15T09:30:00+00:00", False),
        ("instant", "Asia/Kolkata", "2027-01-15T09:30:01+00:00", False),
        ("instant", "Pacific/Honolulu", "2027-01-16T00:59:59+00:00", True),
        ("instant", "Pacific/Honolulu", "2027-01-16T01:00:00+00:00", False),
        ("request", "Asia/Kolkata", "2027-01-14T09:30:00+00:00", True),
        ("request", "Asia/Kolkata", "2027-01-14T09:30:01+00:00", False),
    ],
)
def test_scheduled_check_in_boundaries_search_and_quote(
    client: TestClient,
    monkeypatch: Any,
    mode: str,
    timezone: str,
    now: str,
    allowed: bool,
) -> None:
    monkeypatch.setattr(business_time, "now", lambda: datetime.fromisoformat(now))
    with Session(get_engine()) as db:
        _, listing_id = published(db, timezone=timezone, booking_mode=mode)
    body = {
        "listing_id": str(listing_id),
        "check_in": "2027-01-15",
        "check_out": "2027-01-16",
        "guests": 2,
    }
    search = client.get(
        "/api/v1/listings",
        params={key: value for key, value in body.items() if key != "listing_id"},
    )
    assert search.status_code == 200
    assert [item["id"] for item in search.json()["items"]] == (
        [str(listing_id)] if allowed else []
    )
    quote = client.post("/api/v1/booking-quotes", json=body)
    assert quote.status_code == (200 if allowed else 422)
    if allowed:
        assert quote.json()["quote"]["total_minor"] == 18582
        assert search.json()["items"][0]["stay_price"]["total_minor"] == 18582
    else:
        assert "check_in" in quote.json()["error"]["field_errors"]
        assert "quote" not in quote.json()


@pytest.mark.parametrize(
    ("check_in", "check_out", "field"),
    [
        ("2027-01-14", "2027-01-16", "check_in"),
        ("2027-01-16", "2027-01-16", "check_out"),
        ("2027-01-17", "2027-01-16", "check_out"),
        ("2027-02-30", "2027-03-02", "check_in"),
    ],
)
def test_edited_dates_rejected_by_search_and_direct_quote(
    client: TestClient,
    check_in: str,
    check_out: str,
    field: str,
) -> None:
    with Session(get_engine()) as db:
        _, listing_id = published(db)
    dates = {"check_in": check_in, "check_out": check_out, "guests": 2}
    for response in (
        client.get("/api/v1/listings", params=dates),
        client.post(
            "/api/v1/booking-quotes",
            json={
                **dates,
                "listing_id": str(listing_id),
            },
        ),
    ):
        assert response.status_code == 422
        assert any(
            key.split(".")[-1] == field
            for key in response.json()["error"]["field_errors"]
        )
