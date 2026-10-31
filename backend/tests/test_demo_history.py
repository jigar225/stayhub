import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_discovery import published
from test_services import account

from app.db import get_engine
from app.demo_history import run
from app.models import AppClock, CalendarEntry, Reservation, User


@pytest.mark.parametrize("mode", ["instant", "request"])
def test_import_dry_run_idempotency_and_privacy(mode: str) -> None:
    with Session(get_engine()) as db:
        host, _ = published(db, booking_mode=mode)
        guests = [account(db)[0] for _ in range(5)]
        with db.begin():
            host_email = db.get(User, host.user_id).email  # type: ignore[union-attr]
            emails = [db.get(User, g.user_id).email for g in guests]  # type: ignore[union-attr]
            before = db.get(AppClock, 1).offset_seconds  # type: ignore[union-attr]
    preview = run(get_engine(), host_email, emails)
    assert [r["published"] for r in preview["stays"]] == [2, 2, 2, 0, 0]
    with Session(get_engine()) as db:
        assert db.scalar(select(func.count()).select_from(Reservation)) == 0
    applied = run(get_engine(), host_email, emails, apply=True)
    retry = run(get_engine(), host_email, emails, apply=True)
    assert retry["already_imported"]
    assert applied["stays"] == retry["stays"]
    with Session(get_engine()) as db:
        assert db.scalar(select(func.count()).select_from(Reservation)) == 5
        assert db.get(AppClock, 1).offset_seconds == before  # type: ignore[union-attr]


def test_conflict_rolls_back_entire_import() -> None:
    from datetime import timedelta

    from app.date_rules import local_today

    with Session(get_engine()) as db:
        host, lid = published(db)
        guests = [account(db)[0] for _ in range(5)]
        with db.begin():
            host_email = db.get(User, host.user_id).email  # type: ignore[union-attr]
            emails = [db.get(User, g.user_id).email for g in guests]  # type: ignore[union-attr]
            today = local_today("Europe/Lisbon")
            db.add(
                CalendarEntry(
                    listing_id=lid,
                    kind="block",
                    check_in=today - timedelta(days=7),
                    check_out=today - timedelta(days=6),
                    active=True,
                )
            )
    with pytest.raises(AssertionError, match="overlap"):
        run(get_engine(), host_email, emails, apply=True)
    with Session(get_engine()) as db:
        assert db.scalar(select(func.count()).select_from(Reservation)) == 0
