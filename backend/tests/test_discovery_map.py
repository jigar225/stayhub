"""Viewport discovery uses only the same public grid returned to guests."""

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_discovery import published

from app import calendar_service, discovery_service, listing_service
from app.db import get_engine
from app.discovery_schemas import StayDates
from app.listing_schemas import ListingPatch
from app.models import Listing


def test_viewport_grid_privacy_filters_and_availability(client: TestClient) -> None:
    with Session(get_engine()) as db:
        actor, lid = published(db)
        saved = listing_service.get_listing(db, actor, lid).listing
        listing_service.update_listing(
            db,
            actor,
            lid,
            ListingPatch(
                version=saved.version, latitude=38.723456, longitude=-9.134567
            ),
        )
        point = client.get(f"/api/v1/listings/{lid}/location").json()["location"]
        assert point["latitude"] == 38.72 and point["longitude"] == -9.13
        # Public point is inside; precise point is outside this tiny viewport.
        query = "/api/v1/listings?map=true&west=-9.13001&east=-9.12999&south=38.71999&north=38.72001"
        response = client.get(query + "&destination=Wrong destination")
        assert response.status_code == 200
        assert response.json()["items"][0]["location"] == {
            "latitude": 38.72,
            "longitude": -9.13,
        }
        assert "38.723456" not in response.text and "-9.134567" not in response.text
        assert client.get(query + "&min_price_minor=999999").json()["items"] == []
        assert (
            client.get(
                query.replace("38.71999", "38.72345").replace("38.72001", "38.72346")
            ).json()["items"]
            == []
        )
        calendar_service.create_block(
            db,
            actor,
            lid,
            StayDates(check_in=date(2027, 2, 1), check_out=date(2027, 2, 6)),
        )
        assert (
            client.get(query + "&check_in=2027-02-01&check_out=2027-02-06").json()[
                "items"
            ]
            == []
        )
        saved = listing_service.get_listing(db, actor, lid).listing
        listing_service.unlist(db, actor, lid, saved.version)
        assert client.get(query).json()["items"] == []


def test_antimeridian_null_location_and_result_cap(client: TestClient) -> None:
    with Session(get_engine()) as db:
        actor, lid = published(db)
        assert client.get("/api/v1/listings?map=true").json()["items"] == []
        assert client.get("/api/v1/listings").json()["items"]
        saved = listing_service.get_listing(db, actor, lid).listing
        listing_service.update_listing(
            db,
            actor,
            lid,
            ListingPatch(version=saved.version, latitude=-0.005, longitude=179.996),
        )
        response = client.get(
            "/api/v1/listings?map=true&west=179&south=-1&east=-179&north=1"
        )
        assert len(response.json()["items"]) == 1
        assert response.json()["items"][0]["location"] == {
            "latitude": -0.01,
            "longitude": 180,
        }
        # Clone published fixture metadata only; no arbitrary position inference.
        with db.begin():
            original = db.get(Listing, lid)
            assert original
            for _ in range(51):
                copy = Listing(
                    **{
                        column.name: getattr(original, column.name)
                        for column in Listing.__table__.columns
                        if column.name not in {"id", "created_at", "updated_at"}
                    }
                )
                db.add(copy)
        result = discovery_service.browse(db, limit=100, map_view=True)
        assert (
            len(result.items) == 50
            and result.map_truncated
            and result.next_cursor is None
        )


@pytest.mark.parametrize(
    "suffix",
    [
        "west=1",
        "west=1&east=2&south=3&north=2",
        "west=nan&east=2&south=0&north=1",
        "west=181&east=2&south=0&north=1",
        "west=1&east=1&south=0&north=1",
        "west=1&west=2&east=3&south=0&north=1",
        "cursor=00000000-0000-0000-0000-000000000001",
    ],
)
def test_invalid_viewport(client: TestClient, suffix: str) -> None:
    assert client.get("/api/v1/listings?map=true&" + suffix).status_code == 422
    assert (
        client.get("/api/v1/listings?west=1&east=2&south=0&north=1").status_code == 422
    )
