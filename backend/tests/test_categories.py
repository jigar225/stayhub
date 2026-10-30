"""Real isolated database/storage tests for host-declared category browsing."""

from datetime import timedelta

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session
from test_discovery import END, START, published
from test_services import account

from alembic import command
from app import calendar_service, discovery_service, listing_service
from app.db import get_engine
from app.discovery_schemas import StayDates
from app.errors import ApiError
from app.listing_schemas import ListingPatch


def test_category_filter_composes_and_paginates(client: TestClient) -> None:
    with Session(get_engine()) as db:
        ids = []
        for _ in range(3):
            actor, listing_id = published(db)
            saved = listing_service.get_listing(db, actor, listing_id).listing
            listing_service.update_listing(
                db,
                actor,
                listing_id,
                ListingPatch(
                    version=saved.version, categories=["cabins", "amazing-views"]
                ),
            )
            ids.append(listing_id)
        _, untagged = published(db)
        calendar_service.create_block(
            db,
            actor,
            listing_id,
            StayDates(check_in=START, check_out=END),
        )
        first = discovery_service.browse(db, category="cabins", limit=1)
        assert len(first.items) == 1 and first.next_cursor
        second = discovery_service.browse(
            db,
            category="cabins",
            limit=1,
            cursor=first.items[0].id,
        )
        assert len(second.items) == 1 and second.items[0].id != first.items[0].id
        assert {item.id for item in discovery_service.browse(db).items} == {
            *ids,
            untagged,
        }
        assert discovery_service.browse(db, category="historic").items == []
        assert (
            discovery_service.browse(db, category="cabins", destination="Kyoto").items
            == []
        )
        assert discovery_service.browse(db, category="cabins", guests=3).items == []
        dated = discovery_service.browse(
            db,
            category="cabins",
            check_in=START,
            check_out=END,
        )
        assert {item.id for item in dated.items} == set(ids[:-1])
        adjacent = discovery_service.browse(
            db,
            category="cabins",
            check_in=END,
            check_out=END + timedelta(days=1),
        )
        assert {item.id for item in adjacent.items} == set(ids)
    assert client.get("/api/v1/listings?category=invented").status_code == 422
    result = client.get("/api/v1/listings?category=cabins").json()
    assert len(result["items"]) == 3
    assert result["items"][0]["categories"] == ["cabins", "amazing-views"]


def test_category_validation_ownership_clear_and_omission(client: TestClient) -> None:
    with Session(get_engine()) as db:
        owner, listing_id = published(db)
        other, issue = account(db, host=True)
        saved = listing_service.get_listing(db, owner, listing_id).listing
        assert saved.categories == []
        changed = listing_service.update_listing(
            db,
            owner,
            listing_id,
            ListingPatch(version=saved.version, categories=["beachfront"]),
        ).listing
        changed = listing_service.update_listing(
            db,
            owner,
            listing_id,
            ListingPatch(version=changed.version, title="Preserved owner title"),
        ).listing
        assert changed.categories == ["beachfront"]
        with pytest.raises(ApiError) as forbidden:
            listing_service.update_listing(
                db,
                other,
                listing_id,
                ListingPatch(version=changed.version, categories=["historic"]),
            )
        assert forbidden.value.status == 404
        headers = {"Authorization": f"Bearer {issue.body.access_token}"}
        assert (
            client.patch(
                f"/api/v1/host/listings/{listing_id}",
                headers=headers,
                json={"version": changed.version, "categories": ["historic"]},
            ).status_code
            == 404
        )
        for categories in [["invented"], ["cabins", "cabins"], None, "cabins"]:
            with pytest.raises(ValueError):
                ListingPatch(version=changed.version, categories=categories)
        cleared = listing_service.update_listing(
            db,
            owner,
            listing_id,
            ListingPatch(version=changed.version, categories=[]),
        ).listing
        assert cleared.categories == [] and cleared.title == "Preserved owner title"


def test_additive_migration_preserves_existing_listing() -> None:
    with Session(get_engine()) as db:
        owner, listing_id = published(db)
        before = listing_service.get_listing(db, owner, listing_id).listing
    # Only the explicitly isolated *_test database is configured by conftest.
    command.downgrade(Config("alembic.ini"), "0005_financial_lifecycle")
    try:
        with get_engine().connect() as connection:
            previous = connection.execute(
                text("SELECT title, version, status FROM listings WHERE id=:id"),
                {"id": listing_id},
            ).one()
        assert tuple(previous) == (before.title, before.version, before.status)
    finally:
        command.upgrade(Config("alembic.ini"), "head")
    with Session(get_engine()) as db:
        after = listing_service.get_listing(db, owner, listing_id).listing
        assert after == before and after.categories == []
