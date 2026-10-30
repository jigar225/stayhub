"""M5 policy boundaries, atomic refunds, progression and persisted demo time."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from threading import Barrier
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from test_booking import quote
from test_discovery import published
from test_services import account

from app import (
    auth_service,
    booking_ledger,
    booking_queries,
    booking_service,
    business_time,
    cancellation_service,
    clock_service,
    financial_queries,
    sweep,
)
from app.booking_schemas import DeclineInput, ReservationResponse
from app.config import get_settings
from app.db import get_engine
from app.errors import ApiError
from app.financial_schemas import (
    AdvanceInput,
    CancelInput,
    CancellationQuoteResponse,
    EarningsResponse,
)
from app.models import (
    EventLog,
    IdempotencyRecord,
    Payout,
    Refund,
    Reservation,
    UserRole,
)
from app.policies import DEFINITIONS
from app.refunds import calculate

NOW = datetime(2027, 1, 1, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def clock(monkeypatch: Any) -> None:
    monkeypatch.setattr(business_time, "now", lambda: NOW)


@pytest.mark.parametrize(
    ("policy", "hours", "expected"),
    [
        ("Flexible", 24, 100),
        ("Flexible", 0, 0),
        ("Moderate", 120, 100),
        ("Moderate", 24, 50),
        ("Moderate", 0, 0),
        ("Firm", 720, 100),
        ("Firm", 168, 50),
        ("Firm", 0, 0),
        ("Strict", 336, 50),
        ("Strict", 0, 0),
    ],
)
def test_policy_every_tier_boundary(policy: str, hours: int, expected: int) -> None:
    arrival = NOW + timedelta(days=60)
    for delta in [-1, 0, 1]:
        now = arrival - timedelta(hours=hours) + timedelta(microseconds=delta)
        if now >= arrival:
            with pytest.raises(ValueError):
                calculate(
                    DEFINITIONS[policy],
                    NOW - timedelta(days=10),
                    arrival,
                    now,
                    64000,
                    3500,
                    9450,
                )
            continue
        result = calculate(
            DEFINITIONS[policy],
            NOW - timedelta(days=10),
            arrival,
            now,
            64000,
            3500,
            9450,
        )
        if delta <= 0:
            assert result.refund_percent == expected
        elif hours:
            assert result.refund_percent < expected
        assert (
            76950 - result.total_refund_minor
            == result.host_entitlement_minor + result.platform_entitlement_minor
        )


def test_strict_grace_precedence_and_rounding() -> None:
    arrival = NOW + timedelta(days=40)
    for delta, percent in [(-1, 100), (0, 100), (1, 50)]:
        now = NOW + timedelta(hours=48, microseconds=delta)
        result = calculate(DEFINITIONS["Strict"], NOW, arrival, now, 101, 3, 15)
        assert result.refund_percent == percent
        if percent == 50:
            assert (result.nights_refund_minor, result.guest_fee_refund_minor) == (
                51,
                8,
            )
    assert (
        calculate(
            {"windows": [{"hours_before": 0, "percent": 0}]},
            NOW,
            arrival,
            NOW,
            50,
            0,
            7,
        ).effective_host_fee_minor
        == 2
    )


def booked(
    db: Session, mode: str = "instant", days: int = 10, nights: int = 5
) -> tuple[Any, Any, ReservationResponse]:
    host, lid = published(db, booking_mode=mode)
    guest, _ = account(db)
    start = (NOW + timedelta(days=days)).date()
    return (
        host,
        guest,
        booking_service.pay(
            db,
            guest,
            quote(db, lid, start, start + timedelta(days=nights)),
            str(uuid4()),
        ),
    )


def cancel_preview(db: Session, guest: Any, rid: Any) -> CancelInput:
    result = cancellation_service.preview(db, guest, rid)
    assert isinstance(result, CancellationQuoteResponse)
    return CancelInput(confirmation_token=result.preview.confirmation_token)


@pytest.mark.parametrize(
    ("hours", "refund", "hostnet", "platform"),
    [(120, 76950, 0, 0), (24, 40225, 31040, 5685), (1, 3500, 62080, 11370)],
)
def test_guest_policy_refunds_reconciliation_and_retained_payout(
    hours: int, refund: int, hostnet: int, platform: int, monkeypatch: Any
) -> None:
    with Session(get_engine()) as db:
        host, guest, saved = booked(db)
        # Booked policy definition, not mutable name/current policy, controls math.
        with db.begin():
            stored_row = db.get(Reservation, saved.reservation.id)
            assert stored_row
            stored_row.policy_snapshot = {
                **stored_row.policy_snapshot,
                "definition": DEFINITIONS["Moderate"],
                "name": "Booked custom label",
            }
        at = saved.reservation.scheduled_check_in - timedelta(hours=hours)
        monkeypatch.setattr(business_time, "now", lambda: at)
        body = cancel_preview(db, guest, saved.reservation.id)
        result = cancellation_service.cancel(
            db, guest, saved.reservation.id, body, "cancel"
        )
        assert isinstance(result, ReservationResponse)
        row = result.reservation
        assert row.refund and row.refund.amount_minor == refund
        assert (row.host_entitlement_minor, row.platform_entitlement_minor) == (
            hostnet,
            platform,
        )
        assert row.host_fee_minor == 2025 and row.price.total_minor == 76950
        assert row.payout and row.payout.net_minor == hostnet
        assert not booking_queries.guest_list(db, guest, "upcoming").items
        assert booking_queries.guest_list(db, guest, "cancelled").items
        assert cancellation_service.cancel(db, guest, row.id, body, "cancel") == result
        with pytest.raises(ApiError):
            cancellation_service.cancel(db, guest, row.id, body, "different")
        monkeypatch.setattr(
            business_time, "now", lambda: row.scheduled_check_in + timedelta(days=2)
        )
        value = sweep.run(db)
        assert value.paid == (1 if hostnet else 0)
        assert sweep.run(db).paid == 0
        totals = cast(
            EarningsResponse, financial_queries.payouts(db, host, earnings=True)
        )
        assert totals.totals["paid_minor"] == hostnet
        with db.begin():
            assert db.scalar(select(func.count()).select_from(Refund)) == 1


@pytest.mark.parametrize("kind", ["pending", "host"])
def test_full_cancellation_and_ownership(kind: str) -> None:
    with Session(get_engine()) as db:
        host, guest, saved = booked(
            db, mode="request" if kind == "pending" else "instant"
        )
        other, _ = account(db, host=True)
        with pytest.raises(ApiError) as denied:
            cancellation_service.preview(db, other, saved.reservation.id)
        assert denied.value.status == 404
        if kind == "pending":
            body = cancel_preview(db, guest, saved.reservation.id)
            result = cancellation_service.cancel(
                db, guest, saved.reservation.id, body, "cancel"
            )
        else:
            result = cancellation_service.cancel(
                db,
                host,
                saved.reservation.id,
                DeclineInput(reason="Cannot host"),
                "hostcancel",
                host=True,
            )
        assert isinstance(result, ReservationResponse) and result.reservation.refund
        assert result.reservation.refund.amount_minor == 76950
        assert (
            result.reservation.payout
            and result.reservation.payout.status == "cancelled"
        )


def test_preview_stale_boundary_expiry_tamper_and_checkin(monkeypatch: Any) -> None:
    with Session(get_engine()) as db:
        _, guest, saved = booked(db)
        at = saved.reservation.scheduled_check_in - timedelta(hours=24)
        with db.begin():
            stored_row = db.get(Reservation, saved.reservation.id)
            assert stored_row
            stored_row.policy_snapshot = {
                **stored_row.policy_snapshot,
                "definition": DEFINITIONS["Moderate"],
            }
        monkeypatch.setattr(business_time, "now", lambda: at)
        body = cancel_preview(db, guest, saved.reservation.id)
        monkeypatch.setattr(
            business_time, "now", lambda: at + timedelta(microseconds=1)
        )
        with pytest.raises(ApiError) as stale:
            cancellation_service.cancel(db, guest, saved.reservation.id, body, "stale")
        assert stale.value.code == "stale_cancellation"
        monkeypatch.setattr(business_time, "now", lambda: at + timedelta(minutes=5))
        with pytest.raises(ApiError) as expired:
            cancellation_service.cancel(
                db, guest, saved.reservation.id, body, "expired"
            )
        assert expired.value.code == "cancellation_quote_expired"
        with pytest.raises(ApiError):
            cancellation_service.cancel(
                db,
                guest,
                saved.reservation.id,
                CancelInput(confirmation_token="bad"),
                "bad",
            )
        monkeypatch.setattr(
            business_time, "now", lambda: saved.reservation.scheduled_check_in
        )
        with pytest.raises(ApiError) as late:
            cancellation_service.cancel(db, guest, saved.reservation.id, body, "late")
        assert late.value.code == "cancellation_unavailable"
        with db.begin():
            assert db.scalar(select(func.count()).select_from(Refund)) == 0


def test_pending_preview_overdue_commits_expiry(monkeypatch: Any) -> None:
    with Session(get_engine()) as db:
        _, guest, saved = booked(db, mode="request")
        monkeypatch.setattr(business_time, "now", lambda: NOW + timedelta(hours=24))
        result = cancellation_service.preview(db, guest, saved.reservation.id)
        assert isinstance(result, booking_service.CommittedFailure)
        assert (
            booking_queries.detail(db, guest, saved.reservation.id).reservation.reason
            == "expired"
        )
        assert sweep.run(db).expired == 0


@pytest.mark.parametrize("nights", [1, 5])
def test_large_jump_chronological_progression_payout_and_historical_occupancy(
    nights: int, monkeypatch: Any
) -> None:
    with Session(get_engine()) as db:
        _, guest, saved = booked(db, nights=nights)
        row = saved.reservation
        monkeypatch.setattr(
            business_time, "now", lambda: row.scheduled_check_out + timedelta(days=3)
        )
        result = sweep.run(db)
        assert (result.checked_in, result.completed, result.paid) == (1, 1, 1)
        assert sweep.run(db).paid == 0
        value = booking_queries.detail(db, guest, row.id).reservation
        assert (
            value.state == "completed"
            and value.payout
            and value.payout.status == "paid"
        )
        with db.begin():
            events = list(
                db.scalars(
                    select(EventLog)
                    .where(
                        EventLog.action.in_(
                            [
                                "reservation.checked_in",
                                "reservation.completed",
                                "payout.paid",
                            ]
                        )
                    )
                    .order_by(EventLog.business_at)
                )
            )
            expected = sorted(
                [
                    row.scheduled_check_in,
                    row.scheduled_check_out,
                    row.scheduled_check_in + timedelta(hours=24),
                ]
            )
            assert [e.business_at for e in events] == expected
            assert all(e.recorded_at.year != 2027 for e in events)
            assert db.scalar(
                text("SELECT active FROM calendar_entries WHERE reservation_id=:id"),
                {"id": row.id},
            )


def test_long_stay_pays_before_checkout_and_held_never_pays(monkeypatch: Any) -> None:
    with Session(get_engine()) as db:
        _, guest, saved = booked(db, nights=5)
        _, _, pending = booked(db, mode="request", nights=5)
        monkeypatch.setattr(
            business_time,
            "now",
            lambda: saved.reservation.scheduled_check_in + timedelta(hours=24),
        )
        result = sweep.run(db)
        assert result.paid == 1 and result.expired == 1 and result.completed == 0
        assert (
            booking_queries.detail(db, guest, saved.reservation.id).reservation.state
            == "checked_in"
        )
        with db.begin():
            assert pending.reservation.payout is not None
            pending_payout = db.get(Payout, pending.reservation.payout.id)
            assert pending_payout is not None and pending_payout.status == "cancelled"


@pytest.mark.parametrize("race", ["accept", "expiry", "sweep", "cancel"])
def test_cancellation_races_preserve_money(race: str, monkeypatch: Any) -> None:
    with Session(get_engine()) as db:
        host, guest, saved = booked(
            db, mode="request" if race in {"accept", "expiry"} else "instant"
        )
        body = cancel_preview(db, guest, saved.reservation.id)
    if race == "expiry":
        monkeypatch.setattr(business_time, "now", lambda: NOW + timedelta(hours=24))
    if race == "sweep":
        monkeypatch.setattr(
            business_time,
            "now",
            lambda: saved.reservation.scheduled_check_in + timedelta(days=7),
        )
    barrier = Barrier(2)

    def run(action: int) -> None:
        with Session(get_engine()) as db:
            barrier.wait()
            try:
                if action == 0 or race == "cancel":
                    cancellation_service.cancel(
                        db, guest, saved.reservation.id, body, str(uuid4())
                    )
                elif race == "accept":
                    booking_service.host_decision(
                        db, host, saved.reservation.id, "accept", None, "accept"
                    )
                else:
                    sweep.run(db)
            except ApiError:
                pass

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run, [0, 1]))
    with Session(get_engine()) as db, db.begin():
        row = db.get(Reservation, saved.reservation.id)
        assert row is not None
        refund = db.scalar(select(Refund).where(Refund.reservation_id == row.id))
        payout = db.scalar(select(Payout).where(Payout.reservation_id == row.id))
        assert (
            row.total_minor - (refund.amount_minor if refund else 0)
            == row.host_entitlement_minor + row.platform_entitlement_minor
        )
        assert payout is not None and payout.net_minor == row.host_entitlement_minor
        assert (
            db.scalar(
                select(func.count())
                .select_from(Refund)
                .where(Refund.reservation_id == row.id)
            )
            or 0
        ) <= 1


def test_sweep_crash_rollback_and_cancel_rollback(monkeypatch: Any) -> None:
    with Session(get_engine()) as db:
        _, guest, saved = booked(db)
        body = cancel_preview(db, guest, saved.reservation.id)
        original = booking_service._remember

        def fail(*args: Any, **kwargs: Any) -> None:
            original(*args, **kwargs)
            raise RuntimeError("after flushed cancellation")

        monkeypatch.setattr(booking_service, "_remember", fail)
        with pytest.raises(RuntimeError):
            cancellation_service.cancel(db, guest, saved.reservation.id, body, "fail")
        assert (
            booking_queries.detail(db, guest, saved.reservation.id).reservation.state
            == "confirmed"
        )
        with db.begin():
            assert db.scalar(select(func.count()).select_from(Refund)) == 0
        monkeypatch.setattr(booking_service, "_remember", original)
        monkeypatch.setattr(
            business_time,
            "now",
            lambda: saved.reservation.scheduled_check_out + timedelta(days=2),
        )
        original_event = booking_ledger.event

        def fail_event(*args: Any, **kwargs: Any) -> None:
            original_event(*args, **kwargs)
            if args[2] == "payout.paid":
                raise RuntimeError("crash at payout")

        monkeypatch.setattr(booking_ledger, "event", fail_event)
        with pytest.raises(RuntimeError):
            sweep.run(db)
        assert (
            booking_queries.detail(db, guest, saved.reservation.id).reservation.state
            == "confirmed"
        )
        monkeypatch.setattr(booking_ledger, "event", original_event)
        assert sweep.run(db).paid == 1


def admin(db: Session) -> Any:
    actor, _ = account(db)
    with db.begin():
        db.execute(
            text("DELETE FROM user_roles WHERE user_id=:id"), {"id": actor.user_id}
        )
        db.add(UserRole(user_id=actor.user_id, role="admin"))
    return actor


def test_persisted_clock_idempotency_security_and_aggregates(monkeypatch: Any) -> None:
    monkeypatch.setattr(business_time, "now", business_time._default_now)
    monkeypatch.setenv("DEMO_MODE", "true")
    get_settings.cache_clear()
    with Session(get_engine()) as db:
        actor = admin(db)
        guest, _ = account(db)
        before = clock_service.clock(db, actor)
        first = clock_service.advance(db, actor, AdvanceInput(seconds=86400), "advance")
        replay = clock_service.advance(
            db, actor, AdvanceInput(seconds=86400), "advance"
        )
        assert first.clock == replay.clock and first.clock.offset_seconds == 86400
        assert auth_service.profile(db, guest).user.id == guest.user_id
        with Session(get_engine()) as independent:
            assert clock_service.clock(independent, actor).offset_seconds == 86400
            assert business_time.at(independent) - business_time.real_now() > timedelta(
                hours=23
            )
        with pytest.raises(ApiError):
            clock_service.advance(db, actor, AdvanceInput(seconds=1), "advance")
        with pytest.raises(ApiError):
            clock_service.clock(db, guest)
        log = financial_queries.events(db, actor, action="clock.advanced")
        assert (
            len(log.items) == 1 and log.items[0].recorded_at < log.items[0].business_at
        )
        assert before.offset_seconds == 0
        monkeypatch.setenv("DEMO_MODE", "false")
        get_settings.cache_clear()
        with pytest.raises(ApiError) as disabled:
            clock_service.advance(db, actor, AdvanceInput(seconds=1), "disabled")
        assert disabled.value.code == "demo_disabled"


def test_legacy_m4_replay_shape_unchanged(client: TestClient) -> None:
    with Session(get_engine()) as db:
        host, lid = published(db)
        guest, issue = account(db)
        body = quote(db, lid, date(2027, 2, 1), date(2027, 2, 6))
        saved = booking_service.pay(db, guest, body, "legacy")
        legacy = saved.model_dump(mode="json")
        for field in [
            "payout",
            "financial_version",
            "effective_host_fee_minor",
            "cancelled_at",
        ]:
            legacy["reservation"].pop(field)
        with db.begin():
            record = db.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.actor_id == guest.user_id
                )
            )
            assert record
            record.response_body = legacy
        response = client.post(
            "/api/v1/reservations",
            json=body.model_dump(),
            headers={
                "Authorization": f"Bearer {issue.body.access_token}",
                "Idempotency-Key": "legacy",
            },
        )
        assert response.status_code == 201 and response.json() == legacy
        assert b'"payout"' not in response.content


def test_earnings_totals_are_global_independent_of_page_and_filter(
    monkeypatch: Any,
) -> None:
    with Session(get_engine()) as db:
        host, lid = published(db)
        guest, _ = account(db)
        for day in [1, 10, 20]:
            start = (NOW + timedelta(days=day)).date()
            booking_service.pay(
                db, guest, quote(db, lid, start, start + timedelta(days=1)), str(day)
            )
        monkeypatch.setattr(business_time, "now", lambda: NOW + timedelta(days=5))
        assert sweep.run(db).paid == 1
        first = cast(
            EarningsResponse,
            financial_queries.payouts(db, host, "paid", limit=1, earnings=True),
        )
        assert len(first.items) == 1 and first.totals == {
            "paid_minor": 15811,
            "upcoming_minor": 31622,
            "held_minor": 0,
        }
        filtered = cast(
            EarningsResponse,
            financial_queries.payouts(db, host, "scheduled", limit=1, earnings=True),
        )
        assert filtered.next_cursor and filtered.totals == first.totals


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_clock_advances_exact_sum(same_key: bool, monkeypatch: Any) -> None:
    monkeypatch.setattr(business_time, "now", business_time._default_now)
    monkeypatch.setenv("DEMO_MODE", "true")
    get_settings.cache_clear()
    with Session(get_engine()) as db:
        actor = admin(db)
    barrier = Barrier(2)

    def advance(n: int) -> str:
        with Session(get_engine()) as db:
            barrier.wait()
            try:
                clock_service.advance(
                    db, actor, AdvanceInput(seconds=60), "same" if same_key else str(n)
                )
                return "ok"
            except ApiError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(advance, [0, 1]))
    with Session(get_engine()) as db:
        if same_key:
            clock_service.advance(db, actor, AdvanceInput(seconds=60), "same")
        result = clock_service.clock(db, actor)
        assert result.offset_seconds == (60 if same_key else 120)
        assert result.version == (2 if same_key else 3)
        assert set(results) <= {"ok", "operation_in_progress"}


def test_db_partial_refund_bounds_and_normal_entitlement_guards(
    monkeypatch: Any,
) -> None:
    with Session(get_engine()) as db:
        _, guest, saved = booked(db)
        at = saved.reservation.scheduled_check_in - timedelta(hours=1)
        monkeypatch.setattr(business_time, "now", lambda: at)
        result = cancellation_service.cancel(
            db,
            guest,
            saved.reservation.id,
            cancel_preview(db, guest, saved.reservation.id),
            "cancel",
        )
        assert isinstance(result, ReservationResponse)
        with db.begin():
            for sql in [
                "UPDATE refunds SET amount_minor=original_charge_minor+1,nights_minor=original_charge_minor+1-cleaning_minor-guest_fee_minor",
                "UPDATE refunds SET original_charge_minor=original_charge_minor+1",
                "UPDATE payouts SET status='cancelled' WHERE net_minor>0",
                "UPDATE reservations SET host_entitlement_minor=host_entitlement_minor+100000",
            ]:
                with pytest.raises(IntegrityError), db.begin_nested():
                    db.execute(text(sql))
        _, _, normal = booked(db)
        with db.begin(), pytest.raises(IntegrityError), db.begin_nested():
            db.execute(
                text("UPDATE reservations SET host_entitlement_minor=0 WHERE id=:id"),
                {"id": normal.reservation.id},
            )


def test_s3_urls_remain_on_real_clock_after_business_jump(monkeypatch: Any) -> None:
    with Session(get_engine()) as db:
        _, guest, saved = booked(db)
        monkeypatch.setattr(business_time, "now", lambda: NOW + timedelta(days=100))
        from urllib.parse import parse_qs, urlsplit

        from app.models import now as real_now

        photos = booking_queries.photos(db, guest, saved.reservation.id)
        assert all(
            abs((photo.expires_at - real_now()).total_seconds() - 300) < 5
            for photo in photos.items
        )
        query = parse_qs(urlsplit(photos.items[0].url).query)
        assert query["X-Amz-Expires"] == ["300"]


def test_m4_to_m5_migration_preserves_rows_and_backfills_without_releasing() -> None:
    """Run frozen0005 upgrade in a transaction-local disposable schema.

    Clone actual M4-shaped financial data rather than downgrade shared test DB.
    Rollback removes the entire schema; no development connection is involved.
    """
    import importlib.util

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    with Session(get_engine()) as db:
        host, guest, saved = booked(db, mode="request")
        start = saved.reservation.check_out
        confirmed = booking_service.pay(
            db,
            guest,
            quote(db, saved.reservation.listing_id, start, start + timedelta(days=1)),
            "confirmed",
        )
        booking_service.host_decision(
            db, host, confirmed.reservation.id, "accept", None, "accepted"
        )
        declined = booking_service.pay(
            db,
            guest,
            quote(
                db,
                saved.reservation.listing_id,
                start + timedelta(days=2),
                start + timedelta(days=3),
            ),
            "declined",
        )
        booking_service.host_decision(
            db,
            host,
            declined.reservation.id,
            "decline",
            DeclineInput(reason="Cannot host"),
            "decline",
        )
    engine = get_engine()
    schema = "m5_upgrade_" + uuid4().hex
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
            context = MigrationContext.configure(connection)
            for filename in [
                "0001_auth",
                "0002_listings",
                "0003_calendar_demo",
                "0004_bookings",
            ]:
                spec = importlib.util.spec_from_file_location(
                    filename, f"alembic/versions/{filename}.py"
                )
                assert spec and spec.loader
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                with Operations.context(context):
                    module.upgrade()
            # Copy only columns present in the real frozen M4 schema, preserving
            # actual M4 FK/check constraints and populated full-refund history.
            for name in [
                "users",
                "user_roles",
                "sessions",
                "refresh_tokens",
                "cancellation_policies",
                "listings",
                "listing_photos",
                "reservations",
                "payments",
                "refunds",
                "event_log",
                "idempotency_records",
                "calendar_entries",
            ]:
                columns = list(
                    connection.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns WHERE table_schema=:schema AND table_name=:name ORDER BY ordinal_position"
                        ),
                        {"schema": schema, "name": name},
                    ).scalars()
                )
                names = ",".join('"' + column + '"' for column in columns)
                connection.execute(
                    text(
                        f'INSERT INTO "{schema}".{name} ({names}) SELECT {names} FROM public.{name}'
                    )
                )
            before = {
                name: connection.execute(
                    text(f"SELECT row_to_json(t)::text FROM {name} t")
                )
                .scalars()
                .all()
                for name in ["payments", "refunds", "event_log", "idempotency_records"]
            }
            spec = importlib.util.spec_from_file_location(
                "m5upgrade", "alembic/versions/0005_financial_lifecycle.py"
            )
            assert spec and spec.loader
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            with Operations.context(MigrationContext.configure(connection)):
                module.upgrade()
            assert connection.scalar(text("SELECT count(*) FROM payouts")) == 3
            assert set(
                connection.execute(text("SELECT status FROM payouts")).scalars()
            ) == {"held", "scheduled", "cancelled"}
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM payouts WHERE paid_at IS NOT NULL")
                )
                == 0
            )
            assert connection.scalar(text("SELECT offset_seconds FROM app_clock")) == 0
            for name, rows in before.items():
                if name == "refunds":
                    actual = (
                        connection.execute(
                            text(
                                "SELECT (to_jsonb(t)-'original_charge_minor')::text FROM refunds t"
                            )
                        )
                        .scalars()
                        .all()
                    )
                    import json

                    assert [json.loads(x) for x in actual] == [
                        json.loads(x) for x in rows
                    ]
                    continue
                assert (
                    connection.execute(
                        text(f"SELECT row_to_json(t)::text FROM {name} t")
                    )
                    .scalars()
                    .all()
                    == rows
                )
        finally:
            transaction.rollback()


def test_preview_explains_data_cutoff_and_cleaning(monkeypatch: Any) -> None:
    with Session(get_engine()) as db:
        _, guest, saved = booked(db)
        with db.begin():
            row = db.get(Reservation, saved.reservation.id)
            assert row is not None
            row.policy_snapshot = {
                **row.policy_snapshot,
                "definition": DEFINITIONS["Moderate"],
            }
        for hours in [120, 24, 1]:
            monkeypatch.setattr(
                business_time,
                "now",
                lambda hours=hours: (
                    saved.reservation.scheduled_check_in - timedelta(hours=hours)
                ),
            )
            result = cancellation_service.preview(db, guest, saved.reservation.id)
            assert isinstance(result, CancellationQuoteResponse)
            assert str(120 if hours == 120 else 24) in result.preview.explanation
            assert "Cleaning is refunded in full" in result.preview.explanation


def test_overlapping_sweeps_release_once(monkeypatch: Any) -> None:
    with Session(get_engine()) as db:
        _, guest, saved = booked(db, nights=1)
    monkeypatch.setattr(
        business_time,
        "now",
        lambda: saved.reservation.scheduled_check_out + timedelta(days=2),
    )
    barrier = Barrier(2)

    def run(_: int) -> Any:
        with Session(get_engine()) as db:
            barrier.wait()
            return sweep.run(db)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, [0, 1]))
    assert sum(result.paid for result in results) == 1
    with Session(get_engine()) as db, db.begin():
        assert (
            db.scalar(
                select(func.count())
                .select_from(EventLog)
                .where(EventLog.action == "payout.paid")
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count()).select_from(Payout).where(Payout.status == "paid")
            )
            == 1
        )
