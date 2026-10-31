"""Real PostgreSQL notification privacy, cutoff and source atomicity."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_booking import quote
from test_discovery import published
from test_services import account

from app import booking_service, business_time, notification_service
from app.auth_service import AccessContext
from app.db import get_engine
from app.models import Reservation
from app.notification_models import Notification


def emit(actor: AccessContext, key: str) -> None:
    with Session(get_engine()) as db, db.begin():
        notification_service.notify(
            db,
            actor.user_id,
            "new_message",
            key,
            title="New reservation message",
            href="/messages/test",
        )


def test_recipient_only_read_cutoff_and_pagination(client: TestClient) -> None:
    with Session(get_engine()) as db:
        guest, issue = account(db)
        stranger, stranger_issue = account(db)
    headers = {"Authorization": f"Bearer {issue.body.access_token}"}
    other = {"Authorization": f"Bearer {stranger_issue.body.access_token}"}
    assert client.get("/api/v1/me/notifications").status_code == 401
    for i in range(3):
        emit(guest, str(i))
    emit(stranger, "private")
    page = client.get("/api/v1/me/notifications?limit=2", headers=headers).json()
    assert len(page["items"]) == 2 and page["unread_count"] == 3
    assert (
        len(
            client.get(
                f"/api/v1/me/notifications?before={page['next_cursor']}",
                headers=headers,
            ).json()["items"]
        )
        == 1
    )
    target = page["items"][0]["id"]
    assert (
        client.post(
            f"/api/v1/me/notifications/{target}/read", headers=other, json={}
        ).status_code
        == 404
    )
    emit(guest, "later")
    assert (
        client.post(
            "/api/v1/me/notifications/read-all",
            headers=headers,
            json={"cutoff": page["cutoff"]},
        ).status_code
        == 200
    )
    latest = client.get("/api/v1/me/notifications", headers=headers).json()
    assert latest["unread_count"] == 1 and latest["items"][0]["read_at"] is None
    assert (
        client.post(
            f"/api/v1/me/notifications/{latest['items'][0]['id']}/read",
            headers=headers,
            json={},
        ).status_code
        == 200
    )
    assert (
        client.get("/api/v1/me/notifications", headers=headers).json()["unread_count"]
        == 0
    )
    assert (
        client.get("/api/v1/me/notifications", headers=other).json()["unread_count"]
        == 1
    )


def test_notify_transaction_rollback_self_suppression_and_concurrent_dedup() -> None:
    with Session(get_engine()) as db:
        actor, _ = account(db)
    with pytest.raises(RuntimeError), Session(get_engine()) as db, db.begin():
        notification_service.notify(
            db,
            actor.user_id,
            "new_message",
            "rollback",
            title="Private",
            href="/messages/test",
        )
        raise RuntimeError("source rollback")
    with Session(get_engine()) as db, db.begin():
        notification_service.notify(
            db,
            actor.user_id,
            "new_message",
            "self",
            title="Private",
            href="/messages/test",
            actor_id=actor.user_id,
        )
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: emit(actor, "same-source"), range(2)))
    with Session(get_engine()) as db:
        rows = list(db.scalars(select(Notification)))
        assert len(rows) == 1 and rows[0].source_key == "same-source"
    # New sessions simulate process state loss: all state is persisted.
    with Session(get_engine()) as db:
        assert notification_service.page(db, actor)["unread_count"] == 1


def test_host_accept_notification_is_atomic_and_deduplicated(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        business_time, "now", lambda: datetime(2027, 1, 15, 12, tzinfo=UTC)
    )
    with Session(get_engine()) as db:
        host, lid = published(db, booking_mode="request")
        guest, _ = account(db)
        reservation = booking_service.pay(
            db, guest, quote(db, lid), str(uuid4())
        ).reservation
        key = str(uuid4())
        booking_service.host_decision(db, host, reservation.id, "accept", None, key)
        booking_service.host_decision(db, host, reservation.id, "accept", None, key)
    with Session(get_engine()) as db:
        assert db.scalar(select(func.count()).select_from(Notification)) == 1
        row = db.scalar(select(Notification))
        assert (
            row
            and row.recipient_id == guest.user_id
            and row.href == f"/trips/{reservation.id}"
        )
        assert db.get(Reservation, reservation.id).state == "confirmed"  # type: ignore[union-attr]
