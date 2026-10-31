"""M8 predicates use real isolated PostgreSQL/S3 and existing owner workflows."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_discovery import END, START, published

from app import business_time, calendar_service, listing_service
from app.db import get_engine
from app.discovery_schemas import StayDates
from app.listing_schemas import ListingPatch


@pytest.fixture(autouse=True)
def fixed_business_time(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        business_time, "now", lambda: datetime(2027, 1, 15, 12, tzinfo=UTC)
    )


def update(db: Session, owner: Any, listing_id: UUID, **fields: Any) -> None:
    saved = listing_service.get_listing(db, owner, listing_id).listing
    listing_service.update_listing(
        db, owner, listing_id, ListingPatch(version=saved.version, **fields)
    )


def ids(client: TestClient, query: str = "") -> set[str]:
    response = client.get("/api/v1/listings?" + query)
    assert response.status_code == 200, response.text
    return {row["id"] for row in response.json()["items"]}


def test_filter_combinations_inclusive_boundaries_and_declared_amenities(
    client: TestClient,
) -> None:
    with Session(get_engine()) as db:
        owner, apartment = published(db, nightly=10000)
        update(
            db,
            owner,
            apartment,
            property_type="apartment",
            bedrooms=0,
            beds=1,
            amenities=["  Wi-Fi  ", "KITCHEN", "Air   conditioning"],
            categories=["design"],
        )
        owner, house = published(db, nightly=20000, booking_mode="request")
        update(
            db,
            owner,
            house,
            property_type="house",
            bedrooms=2,
            beds=3,
            amenities=["wifi", "Kitchenette", "Free parking", "Pool"],
            categories=["design"],
        )
        owner, room = published(db, nightly=20001)
        update(
            db,
            owner,
            room,
            property_type="room",
            bedrooms=1,
            beds=2,
            amenities=["Kitchen", "Paid wifi", "Dedicated workspace"],
        )
        owner, no_amenities = published(db, nightly=9999)
        update(db, owner, no_amenities, amenities=[])
    a, h, r, empty = map(str, (apartment, house, room, no_amenities))
    assert ids(client, "place_group=entire") == {a, h, empty}
    assert ids(client, "place_group=private") == {r}
    assert ids(client, "min_price_minor=10000&max_price_minor=20000") == {a, h}
    assert ids(client, "min_price_minor=20000&max_price_minor=20000") == {h}
    assert ids(client, "max_price_minor=9999") == {empty}
    assert ids(client, "max_price_minor=0") == set()
    assert ids(client, "min_bedrooms=2&min_beds=3") == {h}
    assert ids(client, "min_bedrooms=0&min_beds=0") == {a, h, r, empty}
    assert ids(client, "amenity=wifi&amenity=kitchen") == {a}
    assert ids(client, "amenity=wifi&amenity=wifi&amenity=air-conditioning") == {a}
    assert ids(client, "amenity=free-parking&amenity=pool") == {h}
    assert ids(client, "amenity=workspace") == {r}
    assert ids(client, "instant_book=true") == {a, r, empty}
    assert ids(client, "instant_book=false") == {a, h, r, empty}
    assert ids(
        client,
        "place_group=entire&min_price_minor=10000&max_price_minor=20000"
        "&min_bedrooms=0&amenity=wifi&amenity=kitchen&instant_book=true"
        "&category=design&destination=lIsB&guests=2",
    ) == {a}
    assert ids(client, "amenity=wifi&category=design&guests=3") == set()
    assert ids(client, "amenity=wifi&destination=Kyoto") == set()
    assert ids(client, "amenity=wifi&category=cabins") == set()


def test_filtered_pages_skip_nonmatching_rows_before_limit(client: TestClient) -> None:
    with Session(get_engine()) as db:
        listings = [published(db) for _ in range(6)]
        listings.sort(key=lambda item: item[1])
        for index, (owner, listing_id) in enumerate(listings):
            update(
                db,
                owner,
                listing_id,
                nightly_minor=10000 if index < 3 else 20000,
                amenities=["Wifi", "Kitchen"],
            )
    expected = [str(item[1]) for item in listings[3:]]
    seen: list[str] = []
    cursor = None
    for index in range(3):
        query = "min_price_minor=20000&amenity=wifi&amenity=kitchen&limit=1"
        if cursor:
            query += "&cursor=" + cursor
        response = client.get("/api/v1/listings?" + query)
        assert response.status_code == 200, response.text
        page = response.json()
        assert [row["id"] for row in page["items"]] == [expected[index]]
        seen.extend(row["id"] for row in page["items"])
        cursor = page["next_cursor"]
        assert (cursor is not None) == (index < 2)
    assert seen == expected


def test_filters_preserve_availability_local_time_and_price_quotes(
    client: TestClient, monkeypatch: Any
) -> None:
    with Session(get_engine()) as db:
        owner, blocked = published(db, nightly=12800, cleaning=3500)
        update(db, owner, blocked, amenities=["Wifi"], categories=["design"])
        calendar_service.create_block(
            db, owner, blocked, StayDates(check_in=START, check_out=END)
        )
        owner, available = published(db, nightly=12800, cleaning=3500)
        update(db, owner, available, amenities=["Wifi"], categories=["design"])
        owner, request = published(
            db,
            destination="Kyoto",
            timezone="Asia/Tokyo",
            booking_mode="request",
        )
        update(db, owner, request, amenities=["Wifi"])
    query = (
        f"check_in={START}&check_out={END}&guests=2&amenity=wifi"
        "&min_price_minor=12800&max_price_minor=12800&category=design"
    )
    response = client.get("/api/v1/listings?" + query)
    assert response.status_code == 200, response.text
    assert [row["id"] for row in response.json()["items"]] == [str(available)]
    price = response.json()["items"][0]["stay_price"]
    quote = client.post(
        "/api/v1/booking-quotes",
        json={
            "listing_id": str(available),
            "check_in": str(START),
            "check_out": str(END),
            "guests": 2,
        },
    )
    assert quote.status_code == 200, quote.text
    assert all(quote.json()["quote"][key] == value for key, value in price.items())
    assert str(blocked) in ids(
        client,
        f"check_in={END}&check_out={END + timedelta(days=1)}&amenity=wifi&category=design",
    )
    monkeypatch.setattr(
        business_time, "now", lambda: datetime(2027, 1, 15, 23, 30, tzinfo=UTC)
    )
    assert (
        ids(
            client,
            "destination=Kyoto&amenity=wifi&min_price_minor=12800"
            "&check_in=2027-01-16&check_out=2027-01-17",
        )
        == set()
    )
    assert str(request) in ids(
        client,
        "destination=Kyoto&amenity=wifi&check_in=2027-01-17&check_out=2027-01-18",
    )
    assert (
        client.get(
            "/api/v1/listings?destination=Kyoto&amenity=wifi"
            "&check_in=2027-01-15&check_out=2027-01-16"
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "query",
    [
        "place_group=shared",
        "min_price_minor=-1",
        "min_price_minor=10000001",
        "max_price_minor=10000001",
        "min_price_minor=1.25",
        "min_price_minor=1.0",
        "min_price_minor=+1",
        "min_price_minor=200&max_price_minor=100",
        "min_bedrooms=21",
        "min_beds=31",
        "min_beds=1.5",
        "amenity=invented",
        "amenity=Wifi",
        "instant_book=perhaps",
        "instant_book=1",
        "min_price_minor=100&min_price_minor=200",
        "max_price_minor=200&max_price_minor=200",
        "place_group=entire&place_group=private",
        "category=design&category=design",
        "guests=1&guests=2",
        "destination=Lisbon&destination=Kyoto",
        "instant_book=true&instant_book=false",
        "limit=1&limit=2",
    ],
)
def test_invalid_filter_and_ambiguous_scalar_values_return_422(
    client: TestClient, query: str
) -> None:
    response = client.get("/api/v1/listings?" + query)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_error"
