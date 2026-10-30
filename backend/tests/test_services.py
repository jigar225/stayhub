"""Direct service transactions and HTTP guard compatibility on real PostgreSQL."""

from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Session

from app import auth_service, listing_service
from app.db import get_engine
from app.errors import ApiError
from app.listing_schemas import ListingPatch
from app.models import AuthSession, Listing, User, now
from app.schemas import LoginInput, RegisterInput

PASSWORD = "service-test-password!"


def account(
    db: Session, host: bool = False
) -> tuple[auth_service.AccessContext, auth_service.AuthIssue]:
    body = RegisterInput(
        name="Service user", email=f"service-{uuid4()}@example.com", password=PASSWORD
    )
    user = auth_service.register(db, body)
    assert user.user.roles == ["guest"] and not db.in_transaction()
    issue = auth_service.login(db, LoginInput(email=body.email, password=body.password))
    actor = auth_service.access_context(f"Bearer {issue.body.access_token}")
    if host:
        assert set(auth_service.enroll_host(db, actor).user.roles) == {"guest", "host"}
    assert not db.in_transaction()
    return actor, issue


def test_auth_services_commit_reuse_revocation_before_failure_translation() -> None:
    with Session(get_engine()) as db:
        actor, original = account(db, host=True)
        assert auth_service.profile(db, actor).user.id == actor.user_id
        assert (
            auth_service.bootstrap_csrf(db, original.refresh_token).csrf_token
            == original.body.csrf_token
        )
        rotated = auth_service.refresh(
            db, original.refresh_token, original.body.csrf_token
        )
        assert isinstance(rotated, auth_service.AuthIssue)
        assert rotated.refresh_token != original.refresh_token
        assert not db.in_transaction()
        # Return the failure as a value. No caller needs a Request, Response,
        # commit, or special rollback exception to preserve the revocation.
        failure = auth_service.refresh(
            db, original.refresh_token, original.body.csrf_token
        )
        assert isinstance(failure, auth_service.RefreshFailure)
        assert failure.code == "refresh_reused" and not db.in_transaction()
        with Session(get_engine()) as independent:
            revoked = independent.get(AuthSession, actor.session_id)
            assert revoked is not None and revoked.revoked_at is not None
        for token in [original.body.access_token, rotated.body.access_token]:
            with pytest.raises(ApiError) as denied:
                auth_service.profile(db, auth_service.access_context(f"Bearer {token}"))
            assert denied.value.status == 401 and not db.in_transaction()


def test_auth_services_csrf_failure_rolls_back_logout_and_current_expiry() -> None:
    with Session(get_engine()) as db:
        actor, issue = account(db)
        with pytest.raises(ApiError) as denied:
            auth_service.logout(db, issue.refresh_token, "incorrect-csrf")
        assert denied.value.status == 403 and not db.in_transaction()
        assert auth_service.profile(db, actor).user.id == actor.user_id
        expired = replace(actor, expires_at=now() - timedelta(seconds=1))
        with pytest.raises(ApiError) as denied:
            listing_service.create_listing(db, expired)
        assert denied.value.status == 401 and not db.in_transaction()
        auth_service.logout(db, issue.refresh_token, issue.body.csrf_token)
        assert not db.in_transaction()
        with pytest.raises(ApiError) as denied:
            auth_service.profile(db, actor)
        assert denied.value.status == 401


def test_listing_services_own_authorization_versions_and_rollback() -> None:
    with Session(get_engine()) as db:
        owner, _ = account(db, host=True)
        other, _ = account(db, host=True)
        guest, _ = account(db)
        listing = listing_service.create_listing(db, owner).listing
        assert listing.version == 1 and listing.status == "draft"
        assert not db.in_transaction()
        saved = listing_service.update_listing(
            db,
            owner,
            listing.id,
            ListingPatch(version=1, title="Saved through service"),
        ).listing
        assert saved.version == 2 and not db.in_transaction()
        # Complete service operations recheck ownership; a route guard is not
        # required for either private reads or writes.
        for actor, status in [(other, 404), (guest, 403)]:
            with pytest.raises(ApiError) as denied:
                listing_service.get_listing(db, actor, listing.id)
            assert denied.value.status == status and not db.in_transaction()
            with pytest.raises(ApiError) as denied:
                listing_service.update_listing(
                    db,
                    actor,
                    listing.id,
                    ListingPatch(version=2, title="Forbidden change"),
                )
            assert denied.value.status == status and not db.in_transaction()
        with pytest.raises(ApiError) as stale:
            listing_service.update_listing(
                db, owner, listing.id, ListingPatch(version=1, title="Stale change")
            )
        assert stale.value.code == "stale_version" and not db.in_transaction()
        with pytest.raises(ApiError) as incomplete:
            listing_service.publish(db, owner, listing.id, 2)
        assert (
            incomplete.value.code == "publication_invalid" and not db.in_transaction()
        )
        assert listing_service.get_listing(db, owner, listing.id).listing == saved
        with Session(get_engine()) as independent:
            persisted = independent.get(Listing, listing.id)
            assert (
                persisted
                and persisted.title == "Saved through service"
                and persisted.status == "draft"
            )


def test_services_do_not_commit_or_rollback_callers_existing_transaction() -> None:
    email = f"outer-{uuid4()}@example.com"
    with Session(get_engine()) as db:
        actor, _ = account(db, host=True)
        with db.begin():
            db.add(
                User(
                    name="Outer work",
                    email=email,
                    password_hash="test-fixture-not-login",
                )
            )
            db.flush()
            with pytest.raises(InvalidRequestError):
                listing_service.create_listing(db, actor)
            with pytest.raises(InvalidRequestError):
                auth_service.enroll_host(db, actor)
            assert db.in_transaction()
            # Caller work remains untouched and uncommitted by the service.
            with Session(get_engine()) as independent:
                assert (
                    independent.scalar(
                        select(func.count())
                        .select_from(User)
                        .where(User.email == email)
                    )
                    == 0
                )
        with Session(get_engine()) as independent:
            assert (
                independent.scalar(
                    select(func.count()).select_from(User).where(User.email == email)
                )
                == 1
            )


def test_idle_reused_session_reads_current_listing_and_revocation() -> None:
    with Session(get_engine(), expire_on_commit=False) as retained:
        actor, issue = account(retained, host=True)
        listing = listing_service.create_listing(retained, actor).listing
        # Hold actual ORM objects across operations to exercise identity-map
        # staleness that request-scoped sessions normally do not encounter.
        with retained.begin():
            cached_listing = retained.get(Listing, listing.id)
            cached_session = retained.get(AuthSession, actor.session_id)
        assert cached_listing is not None and cached_session is not None
        with Session(get_engine()) as other:
            changed = listing_service.update_listing(
                other,
                actor,
                listing.id,
                ListingPatch(version=1, title="Changed in another transaction"),
            ).listing
        with pytest.raises(ApiError) as stale:
            listing_service.update_listing(
                retained,
                actor,
                listing.id,
                ListingPatch(version=1, title="Stale retained object"),
            )
        assert stale.value.code == "stale_version"
        assert (
            listing_service.get_listing(retained, actor, listing.id).listing == changed
        )
        with Session(get_engine()) as other:
            auth_service.logout(other, issue.refresh_token, issue.body.csrf_token)
        with pytest.raises(ApiError) as revoked:
            auth_service.refresh(retained, issue.refresh_token, issue.body.csrf_token)
        assert revoked.value.status == 401 and not retained.in_transaction()


def test_listing_http_guard_keeps_live_identity_owner_and_origin_precedence(
    client: TestClient,
) -> None:
    with Session(get_engine()) as db:
        owner, owner_issue = account(db, host=True)
        other, other_issue = account(db, host=True)
        guest, guest_issue = account(db)
        listing = listing_service.create_listing(db, owner).listing
        path = f"/api/v1/host/listings/{listing.id}"
        # Wrong-role and other-owner errors historically precede the HTTP Origin
        # guard, even when more than one part of the request is invalid.
        for issue, status in [
            (other_issue, 404),
            (guest_issue, 403),
            (owner_issue, 403),
        ]:
            headers = {
                "Authorization": f"Bearer {issue.body.access_token}",
                "Origin": "https://untrusted.example",
            }
            response = client.patch(
                path, headers=headers, json={"version": 1, "title": "Must not save"}
            )
            assert response.status_code == status
            response = client.post(
                path + "/publish", headers=headers, json={"version": 1}
            )
            assert response.status_code == status
        auth_service.logout(db, owner_issue.refresh_token, owner_issue.body.csrf_token)
        headers = {
            "Authorization": f"Bearer {owner_issue.body.access_token}",
            "Origin": "https://untrusted.example",
        }
        assert (
            client.patch(
                path, headers=headers, json={"version": 1, "title": "Revoked"}
            ).status_code
            == 401
        )
        assert not db.in_transaction()


def test_host_enrollment_http_guard_keeps_revocation_before_origin_and_body(
    client: TestClient,
) -> None:
    with Session(get_engine()) as db:
        actor, issue = account(db)
        auth_service.logout(db, issue.refresh_token, issue.body.csrf_token)
        headers = {
            "Authorization": f"Bearer {issue.body.access_token}",
            "Origin": "https://untrusted.example",
        }
        # A signed-but-revoked identity must remain401, rather than403 Origin or
        # 422 forbidden body, exactly as before the service extraction.
        response = client.post(
            "/api/v1/me/host-role", headers=headers, json={"roles": ["admin"]}
        )
        assert response.status_code == 401
        assert not db.in_transaction()
