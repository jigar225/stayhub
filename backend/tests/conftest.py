import os
from collections.abc import Generator

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from alembic import command

# Tests never default to or truncate the development database.
test_url = os.environ.get("TEST_DATABASE_URL", "")
if not test_url or not (make_url(test_url).database or "").endswith("_test"):
    raise RuntimeError(
        "TEST_DATABASE_URL must point to a separate database ending in _test"
    )
os.environ["DATABASE_URL"] = test_url
os.environ.setdefault("JWT_SECRET", "test-only-" + "x" * 48)
os.environ["TRUSTED_ORIGINS"] = "http://localhost:5173"

from storage_isolation import StorageIsolation, storage_scope  # noqa: E402

from app.config import Settings, get_settings  # noqa: E402

# Settings class import does not instantiate settings or perform storage I/O.
# Reject unsafe raw configuration before app.main initializes/caches settings.
test_storage = StorageIsolation.from_environment(
    str(Settings.model_fields["s3_bucket"].default),
    str(Settings.model_fields["s3_endpoint_url"].default),
)
test_storage.bind_environment()
get_settings.cache_clear()
test_storage.install_guard()

from app.main import app  # noqa: E402
from app.policies import seed_policies  # noqa: E402
from app.security import limiter  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def test_storage_session() -> Generator[None]:
    with storage_scope(test_storage, get_settings.cache_clear, initialize=True):
        yield


@pytest.fixture(autouse=True)
def isolated_storage(test_storage_session: None) -> Generator[None]:
    with storage_scope(test_storage, get_settings.cache_clear):
        yield


@pytest.fixture(scope="session", autouse=True)
def migrated_db(test_storage_session: None) -> Generator[None]:
    command.upgrade(Config("alembic.ini"), "head")
    yield


@pytest.fixture(autouse=True)
def clean_db(isolated_storage: None) -> Generator[None]:
    engine = create_engine(test_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE payouts, event_log, idempotency_records, refunds, payments, reservations, calendar_entries, demo_asset_photos, demo_imports, listing_photos, listings, cancellation_policies, refresh_tokens, sessions, user_roles, users"
                )
            )
        from sqlalchemy.orm import Session

        with Session(engine) as session, session.begin():
            seed_policies(session)
            session.execute(
                text(
                    "UPDATE app_clock SET offset_seconds = 0, version = 1 WHERE id = 1"
                )
            )
        limiter.buckets.clear()
        get_settings.cache_clear()
        yield
    finally:
        engine.dispose()


@pytest.fixture
def client() -> Generator[TestClient]:
    with TestClient(
        app,
        base_url="http://localhost:5173",
        headers={"Origin": "http://localhost:5173"},
    ) as instance:
        yield instance
