"""M4 transactions, concurrency and financial boundaries against real PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from threading import Barrier, Event
from typing import Any
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_discovery import published
from test_services import account

from app import (
    auth_service,
    booking_ledger,
    booking_queries,
    booking_service,
    business_time,
    calendar_service,
    discovery_service,
    listing_service,
)
from app.booking_schemas import DeclineInput, PayInput, ReservationResponse
from app.config import get_settings
from app.db import get_engine
from app.discovery_schemas import QuoteInput, StayDates
from app.errors import ApiError
from app.expire_requests import expire_requests
from app.listing_schemas import ListingPatch
from app.models import (
    CalendarEntry,
    EventLog,
    IdempotencyRecord,
    Listing,
    Payment,
    Refund,
    Reservation,
    UserRole,
)
from app.schemas import LoginInput

NOW = datetime(2027, 1, 15, 12, tzinfo=UTC)
START = date(2027, 2, 1)
END = date(2027, 2, 6)


@pytest.fixture(autouse=True)
def business_clock(monkeypatch: Any) -> None:
    monkeypatch.setattr(business_time, "now", lambda: NOW)


def quote(
    db: Session, listing_id: UUID, start: date = START, end: date = END
) -> PayInput:
    value = discovery_service.quote(
        db, QuoteInput(listing_id=listing_id, check_in=start, check_out=end, guests=2)
    ).quote
    return PayInput(quote_token=value.quote_token)


def counts() -> dict[str, int]:
    with Session(get_engine()) as db:
        return {
            model.__tablename__: int(
                db.scalar(select(func.count()).select_from(model)) or 0
            )
            for model in [
                Reservation,
                Payment,
                Refund,
                CalendarEntry,
                IdempotencyRecord,
                EventLog,
            ]
        }


def auth_header(db: Session, actor: auth_service.AccessContext) -> dict[str, str]:
    profile = auth_service.profile(db, actor)
    issue = auth_service.login(
        db, LoginInput(email=profile.user.email, password="service-test-password!")
    )
    return {
        "Authorization": f"Bearer {issue.body.access_token}",
        "Idempotency-Key": str(uuid4()),
    }


@pytest.mark.parametrize("mode", ["instant", "request"])
def test_pay_exact_snapshots_calendar_party_reads_and_replay(
    client: TestClient, mode: str, monkeypatch: Any
) -> None:
    with Session(get_engine()) as db:
        host, listing_id = published(db, booking_mode=mode)
        guest, issue = account(db)
        body = quote(db, listing_id)
        headers = {
            "Authorization": f"Bearer {issue.body.access_token}",
            "Idempotency-Key": "first-pay",
        }
        response = client.post(
            "/api/v1/reservations", json=body.model_dump(), headers=headers
        )
        assert response.status_code == 201, response.text
        saved = response.json()["reservation"]
        assert saved["state"] == ("pending" if mode == "request" else "confirmed")
        assert saved["price"] == {
            "nights": 5,
            "nightly_minor": 12800,
            "nights_minor": 64000,
            "cleaning_minor": 3500,
            "subtotal_minor": 67500,
            "guest_fee_minor": 9450,
            "total_minor": 76950,
            "currency": "EUR",
        }
        assert (
            saved["host_fee_minor"],
            saved["host_entitlement_minor"],
            saved["platform_entitlement_minor"],
        ) == (2025, 65475, 11475)
        assert saved["payment"]["amount_minor"] == 76950 and saved["refund"] is None
        assert saved["policy"]["definition"]["windows"]
        assert saved["code"].startswith("SH-")
        if mode == "request":
            assert datetime.fromisoformat(saved["request_deadline"]) == NOW + timedelta(
                hours=24
            )
        reservation_id = UUID(saved["id"])
        calendar = calendar_service.calendar(db, host, listing_id, START, END)
        occupied = calendar.items[0]
        assert occupied.kind == "reservation" and occupied.state == saved["state"]
        with pytest.raises(ApiError) as cannot_unblock:
            calendar_service.remove_block(db, host, listing_id, occupied.id)
        assert cannot_unblock.value.status == 404
        assert not discovery_service.browse(db, check_in=START, check_out=END).items
        before = counts()
        monkeypatch.setattr(business_time, "now", lambda: NOW + timedelta(hours=1))
        assert (
            client.post(
                "/api/v1/reservations", json=body.model_dump(), headers=headers
            ).json()
            == response.json()
        )
        assert counts() == before
        assert (
            booking_queries.detail(db, guest, reservation_id).reservation.code
            == saved["code"]
        )
        other, _ = account(db, host=True)
        with pytest.raises(ApiError) as denied:
            booking_queries.detail(db, other, reservation_id)
        assert denied.value.status == 404
        original_listing = listing_service.get_listing(db, host, listing_id).listing
        changed = listing_service.update_listing(
            db,
            host,
            listing_id,
            ListingPatch(
                version=original_listing.version,
                title="Changed after booking",
                nightly_minor=50000,
            ),
        ).listing
        listing_service.unlist(db, host, listing_id, changed.version)
        assert (
            booking_queries.detail(db, guest, reservation_id).model_dump(mode="json")
            == response.json()
        )
        assert len(booking_queries.photos(db, guest, reservation_id).items) == 5
        assert client.get(f"/api/v1/listings/{listing_id}").status_code == 404
        assert (
            booking_queries.guest_list(db, guest, "upcoming").items[0].id
            == reservation_id
        )
        assert booking_queries.host_list(db, host).items[0].id == reservation_id
        today = booking_queries.today(db, host)
        assert len(today.pending if mode == "request" else today.upcoming) == 1
        with db.begin():
            events = list(db.scalars(select(EventLog)))
            assert {e.action for e in events} == {
                "reservation.created",
                "payment.charged",
            }
            assert all(
                e.business_at == NOW and e.recorded_at.year != 2027 for e in events
            )
            assert body.quote_token not in str([e.after for e in events])


def test_idempotency_changed_input_actor_scope_and_no_auth_replay(
    client: TestClient,
) -> None:
    with Session(get_engine()) as db:
        _, listing_id = published(db)
        guest, issue = account(db)
        other, other_issue = account(db)
        body = quote(db, listing_id)
        saved = booking_service.pay(db, guest, body, "same")
        with pytest.raises(ApiError) as changed:
            booking_service.pay(db, guest, PayInput(quote_token="different"), "same")
        assert changed.value.code == "idempotency_conflict"
        with pytest.raises(ApiError) as separate:
            booking_service.pay(db, other, body, "same")
        assert separate.value.code == "availability_conflict"
        assert (
            client.post(
                "/api/v1/reservations",
                json=body.model_dump(),
                headers={"Idempotency-Key": "same"},
            ).status_code
            == 401
        )
        assert (
            client.get(
                f"/api/v1/reservations/{saved.reservation.id}",
                headers={"Authorization": f"Bearer {other_issue.body.access_token}"},
            ).status_code
            == 404
        )
        auth_service.logout(db, issue.refresh_token, issue.body.csrf_token)
        assert (
            client.post(
                "/api/v1/reservations",
                json=body.model_dump(),
                headers={
                    "Authorization": f"Bearer {issue.body.access_token}",
                    "Idempotency-Key": "same",
                },
            ).status_code
            == 401
        )
        assert counts()["payments"] == 1


@pytest.mark.parametrize(
    "case,expected",
    [
        ("tamper", "invalid_quote"),
        ("wrong-purpose", "invalid_quote"),
        ("access", "invalid_quote"),
        ("expired", "quote_expired"),
        ("future-iat", "invalid_quote"),
        ("missing", "invalid_quote"),
        ("bad-type", "invalid_quote"),
        ("stale", "stale_quote"),
        ("unlisted", "stale_quote"),
        ("price", "stale_quote"),
    ],
)
def test_quote_rejections_leave_no_fragments(
    case: str, expected: str, monkeypatch: Any
) -> None:
    with Session(get_engine()) as db:
        host, listing_id = published(db)
        guest, issue = account(db)
        body = quote(db, listing_id)
        settings = get_settings()
        claims = jwt.decode(body.quote_token, options={"verify_signature": False})
        if case == "tamper":
            body = PayInput(quote_token=body.quote_token[:-8] + "abcdefgh")
        elif case == "access":
            body = PayInput(quote_token=issue.body.access_token)
        elif case in {"wrong-purpose", "future-iat", "missing", "bad-type", "price"}:
            if case == "wrong-purpose":
                claims["purpose"] = "access"
            if case == "future-iat":
                claims["iat"] += 1
            if case == "missing":
                del claims["listing_id"]
            if case == "bad-type":
                claims["guests"] = "2"
            if case == "price":
                claims["total_minor"] += 1
            body = PayInput(
                quote_token=jwt.encode(
                    claims, settings.jwt_secret.get_secret_value(), algorithm="HS256"
                )
            )
        elif case == "expired":
            monkeypatch.setattr(
                business_time, "now", lambda: NOW + timedelta(minutes=10)
            )
        else:
            listing = listing_service.get_listing(db, host, listing_id).listing
            if case == "stale":
                listing_service.update_listing(
                    db,
                    host,
                    listing_id,
                    ListingPatch(version=listing.version, title="Changed"),
                )
            else:
                listing_service.unlist(db, host, listing_id, listing.version)
        with pytest.raises(ApiError) as invalid:
            booking_service.pay(db, guest, body, str(uuid4()))
        assert invalid.value.code == expected
        assert counts() == {
            "reservations": 0,
            "payments": 0,
            "refunds": 0,
            "calendar_entries": 0,
            "idempotency_records": 0,
            "event_log": 0,
        }


def test_own_listing_admin_and_transport_input_boundaries(client: TestClient) -> None:
    with Session(get_engine()) as db:
        host, listing_id = published(db)
        body = quote(db, listing_id)
        with pytest.raises(ApiError) as own:
            booking_service.pay(db, host, body, "own")
        assert own.value.code == "own_listing"
        guest, issue = account(db)
        headers = {"Authorization": f"Bearer {issue.body.access_token}"}
        assert (
            client.post(
                "/api/v1/reservations", json=body.model_dump(), headers=headers
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v1/reservations",
                json={**body.model_dump(), "guest_id": str(host.user_id)},
                headers={**headers, "Idempotency-Key": "x"},
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/v1/reservations",
                json=body.model_dump(),
                headers={
                    **headers,
                    "Idempotency-Key": "x",
                    "Origin": "https://evil.example",
                },
            ).status_code
            == 403
        )
        with db.begin():
            db.execute(
                text("DELETE FROM user_roles WHERE user_id = :id"),
                {"id": guest.user_id},
            )
            db.add(UserRole(user_id=guest.user_id, role="admin"))
        assert (
            client.post(
                "/api/v1/reservations",
                json=body.model_dump(),
                headers={**headers, "Idempotency-Key": "x"},
            ).status_code
            == 403
        )
        assert counts()["payments"] == 0


def test_two_guests_race_one_charge_and_adjacent_booking() -> None:
    with Session(get_engine()) as db:
        _, listing_id = published(db)
        guests = [account(db)[0], account(db)[0]]
        body = quote(db, listing_id)
    barrier = Barrier(2)

    def book(actor: auth_service.AccessContext) -> str:
        with Session(get_engine()) as db:
            barrier.wait()
            try:
                return str(
                    booking_service.pay(db, actor, body, str(uuid4())).reservation.id
                )
            except ApiError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(book, guests))
    assert outcomes.count("availability_conflict") == 1
    assert counts() == {
        "reservations": 1,
        "payments": 1,
        "refunds": 0,
        "calendar_entries": 1,
        "idempotency_records": 1,
        "event_log": 2,
    }
    with Session(get_engine()) as db:
        booking_service.pay(
            db,
            guests[0],
            quote(db, listing_id, END, END + timedelta(days=1)),
            "adjacent",
        )
    assert counts()["payments"] == 2


def test_booking_vs_host_block_race() -> None:
    with Session(get_engine()) as db:
        host, listing_id = published(db)
        guest, _ = account(db)
        body = quote(db, listing_id)
    barrier = Barrier(2)

    def compete(kind: str) -> str:
        with Session(get_engine()) as db:
            barrier.wait()
            try:
                if kind == "booking":
                    booking_service.pay(db, guest, body, "book")
                else:
                    calendar_service.create_block(
                        db, host, listing_id, StayDates(check_in=START, check_out=END)
                    )
                return kind
            except ApiError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(compete, ["booking", "block"]))
    assert outcomes.count("availability_conflict") == 1
    assert counts()["calendar_entries"] == 1
    assert counts()["payments"] == (1 if "booking" in outcomes else 0)


def test_same_key_concurrent_then_retry_one_result(monkeypatch: Any) -> None:
    with Session(get_engine()) as db:
        _, listing_id = published(db)
        guest, _ = account(db)
        body = quote(db, listing_id)
    reached, release = Event(), Event()
    original = booking_service._locked_listing

    def paused(db: Session, listing_id: UUID) -> Listing:
        reached.set()
        assert release.wait(10)
        return original(db, listing_id)

    monkeypatch.setattr(booking_service, "_locked_listing", paused)

    def first() -> ReservationResponse:
        with Session(get_engine()) as db:
            return booking_service.pay(db, guest, body, "same")

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(first)
        assert reached.wait(10)
        try:
            with Session(get_engine()) as db, pytest.raises(ApiError) as processing:
                booking_service.pay(db, guest, body, "same")
            assert processing.value.code == "operation_in_progress"
        finally:
            release.set()
        saved = future.result()
    with Session(get_engine()) as db:
        assert booking_service.pay(db, guest, body, "same") == saved
    assert counts()["payments"] == 1 and counts()["event_log"] == 2


@pytest.mark.parametrize("decision", ["accept", "decline"])
def test_host_decisions_full_refund_and_replay(decision: str) -> None:
    with Session(get_engine()) as db:
        host, listing_id = published(db, booking_mode="request")
        guest, _ = account(db)
        saved = booking_service.pay(db, guest, quote(db, listing_id), "book")
        rid = saved.reservation.id
        body = (
            DeclineInput(reason="  Plans cannot be accommodated  ")
            if decision == "decline"
            else None
        )
        result = booking_service.host_decision(db, host, rid, decision, body, "decide")
        assert isinstance(result, ReservationResponse)
        assert result.reservation.state == (
            "confirmed" if decision == "accept" else "declined"
        )
        before = counts()
        assert (
            booking_service.host_decision(db, host, rid, decision, body, "decide")
            == result
        )
        assert counts() == before and before["payments"] == 1
        with pytest.raises(ApiError) as again:
            booking_service.host_decision(db, host, rid, decision, body, "new-key")
        assert again.value.code == "invalid_state"
        if decision == "decline":
            value = result.reservation
            assert value.refund is not None and value.refund.amount_minor == 76950
            assert (
                value.refund.nights_minor,
                value.refund.cleaning_minor,
                value.refund.guest_fee_minor,
            ) == (64000, 3500, 9450)
            assert value.host_entitlement_minor == value.platform_entitlement_minor == 0
            assert discovery_service.browse(db, check_in=START, check_out=END).items
            assert before["refunds"] == 1 and before["event_log"] == 4
        else:
            assert before["refunds"] == 0 and before["event_log"] == 3


def test_accept_at_exact_deadline_commits_expiry_before_409(
    client: TestClient, monkeypatch: Any
) -> None:
    with Session(get_engine()) as db:
        host, listing_id = published(db, booking_mode="request")
        guest, _ = account(db)
        saved = booking_service.pay(db, guest, quote(db, listing_id), "book")
        headers = auth_header(db, host)
    monkeypatch.setattr(business_time, "now", lambda: NOW + timedelta(hours=24))
    response = client.post(
        f"/api/v1/host/reservations/{saved.reservation.id}/accept",
        json={},
        headers=headers,
    )
    assert (
        response.status_code == 409
        and response.json()["error"]["code"] == "request_expired"
    )
    with Session(get_engine()) as db:
        row = booking_queries.detail(db, guest, saved.reservation.id).reservation
        assert (
            row.state == "declined"
            and row.reason == "expired"
            and row.refund
            and row.refund.amount_minor == 76950
        )
        assert discovery_service.browse(db, check_in=START, check_out=END).items
        assert expire_requests(db)["expired"] == 0
    assert counts()["refunds"] == 1 and counts()["event_log"] == 4


@pytest.mark.parametrize(
    "race", ["accept-decline", "accept-expiry", "duplicate-expiry"]
)
def test_host_and_expiry_races(race: str, monkeypatch: Any) -> None:
    with Session(get_engine()) as db:
        host, listing_id = published(db, booking_mode="request")
        guest, _ = account(db)
        saved = booking_service.pay(db, guest, quote(db, listing_id), "book")
    if race != "accept-decline":
        monkeypatch.setattr(business_time, "now", lambda: NOW + timedelta(hours=24))
    barrier = Barrier(2)
    actions = (
        ["accept", "decline"]
        if race == "accept-decline"
        else ["accept", "expire"]
        if race == "accept-expiry"
        else ["expire", "expire"]
    )

    def decide(action: str) -> object:
        with Session(get_engine()) as db:
            barrier.wait()
            if action == "expire":
                return expire_requests(db)
            try:
                return booking_service.host_decision(
                    db,
                    host,
                    saved.reservation.id,
                    action,
                    DeclineInput(reason="Cannot host") if action == "decline" else None,
                    str(uuid4()),
                )
            except ApiError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(decide, actions))
    with Session(get_engine()) as db:
        row = booking_queries.detail(db, guest, saved.reservation.id).reservation
        if race == "accept-decline":
            assert (
                row.state in {"confirmed", "declined"}
                and results.count("invalid_state") == 1
            )
        else:
            assert row.state == "declined" and row.reason == "expired"
    assert counts()["payments"] == 1
    assert counts()["refunds"] == (1 if row.state == "declined" else 0)
    assert counts()["event_log"] == (4 if row.state == "declined" else 3)


def test_pay_failure_injection_rolls_every_fragment_back(monkeypatch: Any) -> None:
    with Session(get_engine()) as db:
        _, listing_id = published(db)
        guest, _ = account(db)
        body = quote(db, listing_id)
        original = booking_service._remember

        def fail_after_flush(*args: Any, **kwargs: Any) -> None:
            original(*args, **kwargs)
            raise RuntimeError("injected failure after writes")

        monkeypatch.setattr(booking_service, "_remember", fail_after_flush)
        with pytest.raises(RuntimeError):
            booking_service.pay(db, guest, body, "fail")
        assert not db.in_transaction()
        assert not any(counts().values())
        monkeypatch.setattr(booking_service, "_remember", original)
        booking_service.pay(db, guest, body, "fail")
    assert counts()["payments"] == 1


def test_refund_failure_injection_rolls_state_money_occupancy_events_back(
    monkeypatch: Any,
) -> None:
    with Session(get_engine()) as db:
        host, listing_id = published(db, booking_mode="request")
        guest, _ = account(db)
        saved = booking_service.pay(db, guest, quote(db, listing_id), "book")
        before = counts()
        original = booking_ledger.decline

        def failed(*args: Any, **kwargs: Any) -> None:
            original(*args, **kwargs)
            raise RuntimeError("injected after refund flush")

        monkeypatch.setattr(booking_ledger, "decline", failed)
        with pytest.raises(RuntimeError):
            booking_service.host_decision(
                db,
                host,
                saved.reservation.id,
                "decline",
                DeclineInput(reason="No"),
                "decline",
            )
        assert counts() == before
        row = booking_queries.detail(db, guest, saved.reservation.id).reservation
        assert row.state == "pending" and row.host_entitlement_minor == 65475
        assert not discovery_service.browse(db, check_in=START, check_out=END).items


def test_db_money_reference_and_occupancy_constraints() -> None:
    with Session(get_engine()) as db:
        _, listing_id = published(db)
        guest, _ = account(db)
        saved = booking_service.pay(db, guest, quote(db, listing_id), "book")
        with db.begin():
            with pytest.raises(IntegrityError), db.begin_nested():
                db.execute(
                    text(
                        "UPDATE payments SET amount_minor = amount_minor + 1 WHERE reservation_id = :id"
                    ),
                    {"id": saved.reservation.id},
                )
            with pytest.raises(IntegrityError), db.begin_nested():
                db.add(
                    CalendarEntry(
                        listing_id=listing_id,
                        kind="reservation",
                        reservation_id=saved.reservation.id,
                        check_in=END,
                        check_out=END + timedelta(days=1),
                        active=True,
                    )
                )
                db.flush()
            with pytest.raises(IntegrityError), db.begin_nested():
                db.add(
                    Refund(
                        payment_id=saved.reservation.payment.id,
                        reservation_id=saved.reservation.id,
                        operation_id="bad-refund",
                        amount_minor=76951,
                        nights_minor=64001,
                        cleaning_minor=3500,
                        guest_fee_minor=9450,
                        reason="bad",
                        refunded_at=NOW,
                    )
                )
                db.flush()


def test_host_authorization_blank_reason_and_pagination(client: TestClient) -> None:
    with Session(get_engine()) as db:
        host, listing_id = published(db, booking_mode="request")
        other, _ = account(db, host=True)
        guest, _ = account(db)
        first = booking_service.pay(db, guest, quote(db, listing_id), "one")
        second = booking_service.pay(
            db, guest, quote(db, listing_id, END, END + timedelta(days=1)), "two"
        )
        for actor, status in [(other, 404), (guest, 403)]:
            response = client.post(
                f"/api/v1/host/reservations/{first.reservation.id}/accept",
                json={},
                headers=auth_header(db, actor),
            )
            assert response.status_code == status
        headers = auth_header(db, host)
        assert (
            client.post(
                f"/api/v1/host/reservations/{first.reservation.id}/decline",
                json={"reason": "   "},
                headers=headers,
            ).status_code
            == 422
        )
        page = booking_queries.guest_list(db, guest, limit=1)
        assert page.next_cursor
        rest = booking_queries.guest_list(
            db, guest, limit=1, cursor=UUID(page.next_cursor)
        )
        assert {page.items[0].id, rest.items[0].id} == {
            first.reservation.id,
            second.reservation.id,
        }
        assert rest.next_cursor is None
        today = booking_queries.today(db, host, limit=1)
        assert len(today.pending) == 1 and today.next_cursor
        assert counts()["refunds"] == 0


@pytest.mark.parametrize(
    ("mode", "initial", "at", "allowed"),
    [
        ("instant", "2027-01-15T09:29:58+00:00", "2027-01-15T09:29:59+00:00", True),
        ("instant", "2027-01-15T09:29:58+00:00", "2027-01-15T09:30:00+00:00", False),
        ("instant", "2027-01-15T09:29:58+00:00", "2027-01-15T09:30:01+00:00", False),
        ("request", "2027-01-14T09:29:59+00:00", "2027-01-14T09:30:00+00:00", True),
        ("request", "2027-01-14T09:29:59+00:00", "2027-01-14T09:30:01+00:00", False),
    ],
)
def test_pay_revalidates_non_utc_instant_and_request_boundaries(
    mode: str,
    initial: str,
    at: str,
    allowed: bool,
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(business_time, "now", lambda: datetime.fromisoformat(initial))
    with Session(get_engine()) as db:
        _, listing_id = published(db, timezone="Asia/Kolkata", booking_mode=mode)
        guest, _ = account(db)
        body = quote(db, listing_id, date(2027, 1, 15), date(2027, 1, 16))
        monkeypatch.setattr(business_time, "now", lambda: datetime.fromisoformat(at))
        if allowed:
            result = booking_service.pay(db, guest, body, "boundary")
            assert result.reservation.scheduled_check_in == datetime(
                2027, 1, 15, 9, 30, tzinfo=UTC
            )
            assert result.reservation.created_at == datetime.fromisoformat(at)
        else:
            with pytest.raises(ApiError) as rejected:
                booking_service.pay(db, guest, body, "boundary")
            assert (
                rejected.value.status == 422
                and rejected.value.field_errors
                and "check_in" in rejected.value.field_errors
            )
            assert not any(counts().values())


@pytest.mark.parametrize(
    "case",
    [
        "issuer",
        "audience",
        "algorithm",
        "malformed-date",
        "past-date",
        "reversed-date",
        "capacity",
    ],
)
def test_pay_token_and_date_schema_independent_revalidation(
    case: str, client: TestClient
) -> None:
    with Session(get_engine()) as db:
        _, listing_id = published(db)
        guest, _ = account(db)
        body = quote(db, listing_id)
        # A booking quote cannot authenticate as a session access token.
        assert (
            client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {body.quote_token}"},
            ).status_code
            == 401
        )
        data = jwt.decode(body.quote_token, options={"verify_signature": False})
        if case == "issuer":
            data["iss"] = "wrong-issuer"
        if case == "audience":
            data["aud"] = "wrong-audience"
        if case == "malformed-date":
            data["check_in"] = "2027-02-30"
        if case == "past-date":
            data["check_in"] = "2027-01-14"
        if case == "reversed-date":
            data["check_in"], data["check_out"] = data["check_out"], data["check_in"]
        if case == "capacity":
            data["guests"] = 3
        token = jwt.encode(
            data,
            get_settings().jwt_secret.get_secret_value(),
            algorithm="HS384" if case == "algorithm" else "HS256",
        )
        with pytest.raises(ApiError) as rejected:
            booking_service.pay(db, guest, PayInput(quote_token=token), "bad-token")
        assert rejected.value.status == 422
        assert not any(counts().values())


def test_pay_success_replay_after_terminal_refund_and_guest_role_revocation() -> None:
    with Session(get_engine()) as db:
        host, listing_id = published(db, booking_mode="request")
        guest, _ = account(db)
        body = quote(db, listing_id)
        original = booking_service.pay(db, guest, body, "paid")
        booking_service.host_decision(
            db,
            host,
            original.reservation.id,
            "decline",
            DeclineInput(reason="Cannot host"),
            "declined",
        )
        before = counts()
        assert booking_service.pay(db, guest, body, "paid") == original
        assert counts() == before
        with db.begin():
            db.execute(
                text("DELETE FROM user_roles WHERE user_id = :id AND role = 'guest'"),
                {"id": guest.user_id},
            )
        with pytest.raises(ApiError) as revoked:
            booking_service.pay(db, guest, body, "paid")
        assert revoked.value.status == 403 and counts() == before


def test_sweep_batch_boundary_system_event_and_idempotent_runs(
    monkeypatch: Any,
) -> None:
    with Session(get_engine()) as db:
        _, listing_id = published(db, booking_mode="request")
        guest, _ = account(db)
        for offset in [0, 5]:
            booking_service.pay(
                db,
                guest,
                quote(
                    db,
                    listing_id,
                    START + timedelta(days=offset),
                    END + timedelta(days=offset),
                ),
                str(offset),
            )
        monkeypatch.setattr(
            business_time,
            "now",
            lambda: NOW + timedelta(hours=24) - timedelta(microseconds=1),
        )
        assert expire_requests(db, 1) == {"scanned": 0, "expired": 0, "deferred": 0}
        monkeypatch.setattr(business_time, "now", lambda: NOW + timedelta(hours=24))
        assert expire_requests(db, 1) == {"scanned": 1, "expired": 1, "deferred": 0}
        assert expire_requests(db, 1) == {"scanned": 1, "expired": 1, "deferred": 0}
        assert expire_requests(db, 1) == {"scanned": 0, "expired": 0, "deferred": 0}
        with db.begin():
            events = list(
                db.scalars(
                    select(EventLog).where(EventLog.action == "reservation.expired")
                )
            )
            assert len(events) == 2 and all(
                e.actor_id is None and e.system_identity == "request-expiry"
                for e in events
            )
        assert counts()["refunds"] == 2
