"""Real-Postgres double-blind boundaries, publication races and money isolation."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_booking import auth_header
from test_financial import NOW, booked
from test_services import account

from app import business_time, review_service, sweep
from app.db import get_engine
from app.errors import ApiError
from app.models import Reservation
from app.notification_models import Notification
from app.review_models import Review, ReviewWindow
from app.review_schemas import CATEGORIES, ReviewInput


def guest_review(text: str = "A thoughtful stay.", overall: int = 4) -> ReviewInput:
    return ReviewInput(
        text=text, overall=overall, categories=dict.fromkeys(CATEGORIES, overall)
    )


def completed_stay(db: Session, monkeypatch: Any) -> tuple[Any, Any, Any, Any]:
    monkeypatch.setattr(business_time, "now", lambda: NOW)
    host, guest, saved = booked(db)
    at = saved.reservation.scheduled_check_out
    monkeypatch.setattr(business_time, "now", lambda: at)
    sweep.run(db)
    return host, guest, saved.reservation, at


def test_double_blind_transport_public_aggregate_and_immutable(
    client: TestClient, monkeypatch: Any
) -> None:
    with Session(get_engine()) as db:
        host, guest, r, at = completed_stay(db, monkeypatch)
        gh, hh = auth_header(db, guest), auth_header(db, host)
        outsider, _ = account(db)
        oh = auth_header(db, outsider)
        before = db.get(Reservation, r.id)
        assert before
        money = (
            before.financial_version,
            before.host_entitlement_minor,
            before.platform_entitlement_minor,
        )
        db.rollback()
        first = client.post(
            f"/api/v1/reservations/{r.id}/reviews",
            headers=gh,
            json=guest_review("Private guest text.").model_dump(),
        )
        assert first.status_code == 201, first.text
        assert first.json()["own"]["published_at"] is None
        assert first.json()["counterpart"] is None
        hidden = client.get(f"/api/v1/reservations/{r.id}/reviews", headers=hh).json()
        assert (
            hidden["own"] is None
            and hidden["counterpart"] is None
            and hidden["status"] == "open"
        )
        assert "Private guest text." not in str(hidden)
        public = client.get(f"/api/v1/listings/{r.listing_id}/reviews").json()
        assert public == {"items": [], "average": None, "count": 0, "next_cursor": None}
        assert (
            client.get(f"/api/v1/reservations/{r.id}/reviews", headers=oh).status_code
            == 404
        )
        assert (
            client.post(
                f"/api/v1/reservations/{r.id}/reviews",
                headers=oh,
                json=guest_review().model_dump(),
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/api/v1/reservations/{r.id}/reviews",
                headers=gh,
                json=guest_review("Edited").model_dump(),
            ).status_code
            == 409
        )
        assert (
            client.post(
                f"/api/v1/reservations/{r.id}/reviews",
                headers=hh,
                json=guest_review().model_dump(),
            ).status_code
            == 422
        )
        second = client.post(
            f"/api/v1/reservations/{r.id}/reviews",
            headers=hh,
            json={"text": "A considerate guest."},
        )
        assert second.status_code == 201, second.text
        assert second.json()["counterpart"]["text"] == "Private guest text."
        assert second.json()["own"]["published_at"] is not None
        public = client.get(f"/api/v1/listings/{r.listing_id}/reviews").json()
        assert public["count"] == 1 and public["average"] == 4
        assert [item["author_role"] for item in public["items"]] == ["guest"]
        after = db.get(Reservation, r.id)
        assert after
        assert (
            after.financial_version,
            after.host_entitlement_minor,
            after.platform_entitlement_minor,
        ) == money
        assert after.completed_at == at
        publications = list(
            db.scalars(
                select(Notification).where(Notification.kind == "review_publication")
            )
        )
        assert len(publications) == 1 and publications[0].recipient_id == guest.user_id
        assert all("Private guest text." not in n.title for n in publications)


@pytest.mark.parametrize("delta,allowed", [(-1, True), (0, False), (1, False)])
def test_exact_business_deadline(monkeypatch: Any, delta: int, allowed: bool) -> None:
    with Session(get_engine()) as db:
        host, guest, r, at = completed_stay(db, monkeypatch)
        clock = at + timedelta(days=14, microseconds=delta)
        monkeypatch.setattr(business_time, "now", lambda: clock)
        if allowed:
            assert (
                review_service.submit(db, guest, r.id, guest_review()).status
                == "submitted"
            )
        else:
            with pytest.raises(ApiError, match="14-day") as failure:
                review_service.submit(db, guest, r.id, guest_review())
            assert failure.value.status == 409
        review_service.sweep_reviews(db)
        page = review_service.listing_reviews(db, r.listing_id)
        assert page.count == 0


def test_expiry_reminder_dedup_and_restart_visibility(monkeypatch: Any) -> None:
    with Session(get_engine()) as db:
        host, guest, r, at = completed_stay(db, monkeypatch)
        review_service.submit(db, guest, r.id, guest_review())
        # Reminder is due inclusively48h before closure; only the nonauthor receives it.
        before = at + timedelta(days=12, microseconds=-1)
        monkeypatch.setattr(business_time, "now", lambda: before)
        review_service.sweep_reviews(db)
        with db.begin():
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(Notification)
                    .where(Notification.kind == "review_reminder")
                )
                == 0
            )
        due = at + timedelta(days=12)
        monkeypatch.setattr(business_time, "now", lambda: due)
        review_service.sweep_reviews(db)
        review_service.sweep_reviews(db)
        with db.begin():
            reminders = list(
                db.scalars(
                    select(Notification).where(Notification.kind == "review_reminder")
                )
            )
            assert len(reminders) == 1 and reminders[0].recipient_id == host.user_id
        deadline = at + timedelta(days=14)
        monkeypatch.setattr(business_time, "now", lambda: deadline)
        sweep.run(db)
        sweep.run(db)
        assert review_service.listing_reviews(db, r.listing_id).count == 1
        rid, lid = r.id, r.listing_id
    # New connection/session sees committed publication and checkpoint state.
    with Session(get_engine()) as restarted:
        assert review_service.listing_reviews(restarted, lid).average == 4
        with restarted.begin():
            assert restarted.get(ReviewWindow, rid).closed_at == deadline  # type: ignore[union-attr]
            assert (
                restarted.scalar(
                    select(func.count())
                    .select_from(Notification)
                    .where(Notification.kind == "review_publication")
                )
                == 2
            )
            assert (
                restarted.scalar(
                    select(func.count())
                    .select_from(Notification)
                    .where(Notification.kind == "review_eligibility")
                )
                == 2
            )


@pytest.mark.parametrize(
    "state",
    ["pending", "confirmed", "cancelled_by_guest", "cancelled_by_host", "declined"],
)
def test_noncompleted_and_self_reviews_rejected(monkeypatch: Any, state: str) -> None:
    with Session(get_engine()) as db:
        monkeypatch.setattr(business_time, "now", lambda: NOW)
        _, guest, saved = booked(db)
        rid = saved.reservation.id
        with db.begin():
            row = db.get(Reservation, rid)
            assert row
            row.state = state
            if state in {"declined", "cancelled_by_guest", "cancelled_by_host"}:
                row.effective_host_fee_minor = row.host_entitlement_minor = (
                    row.platform_entitlement_minor
                ) = 0
        with pytest.raises(ApiError) as failure:
            review_service.submit(db, guest, rid, guest_review())
        assert failure.value.status == 409
        # The reservation invariant rejects a self-booking before any review exists.
        with pytest.raises(IntegrityError), db.begin():
            row = db.get(Reservation, rid)
            assert row
            row.host_id = row.guest_id


def test_concurrent_duplicates_and_publication(monkeypatch: Any) -> None:
    with Session(get_engine()) as db:
        host, guest, r, at = completed_stay(db, monkeypatch)
        rid, lid = r.id, r.listing_id
    barrier = Barrier(2)

    def submit_same() -> int:
        barrier.wait()
        with Session(get_engine()) as session:
            try:
                review_service.submit(session, guest, rid, guest_review())
                return 201
            except ApiError as error:
                return error.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: submit_same(), range(2))) == [201, 409]
    deadline = at + timedelta(days=14)
    monkeypatch.setattr(business_time, "now", lambda: deadline)

    def publish() -> None:
        barrier.wait()
        with Session(get_engine()) as session:
            review_service.sweep_reviews(session)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: publish(), range(2)))
    with Session(get_engine()) as db:
        assert review_service.listing_reviews(db, lid).count == 1
        with db.begin():
            assert db.scalar(select(func.count()).select_from(Review)) == 1
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(Notification)
                    .where(Notification.kind == "review_publication")
                )
                == 2
            )


def test_host_feed_ownership_and_double_blind(
    client: TestClient, monkeypatch: Any
) -> None:
    with Session(get_engine()) as db:
        host, guest, r, _ = completed_stay(db, monkeypatch)
        other, _ = account(db, host=True)
        hh, gh, oh = (
            auth_header(db, host),
            auth_header(db, guest),
            auth_header(db, other),
        )
        review_service.submit(db, guest, r.id, guest_review())
        hidden = client.get("/api/v1/host/reviews", headers=hh)
        assert hidden.status_code == 200
        assert hidden.json()["count"] == 0
        assert hidden.json()["items"] == []
        assert client.get("/api/v1/host/reviews", headers=gh).status_code == 403
        review_service.submit(db, host, r.id, ReviewInput(text="A considerate guest."))
        shown = client.get("/api/v1/host/reviews", headers=hh)
        assert shown.status_code == 200
        assert shown.json()["count"] == 1
        assert shown.json()["average"] == 4
        assert shown.json()["items"][0]["listing_id"] == str(r.listing_id)
        assert shown.json()["items"][0]["author_role"] == "guest"
        assert shown.json()["items"][0]["listing_title"]
        assert client.get("/api/v1/host/reviews", headers=oh).json()["items"] == []
