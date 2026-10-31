"""Existing reservation/policy data survives the additive communication upgrade."""

from datetime import timedelta
from typing import Any
from uuid import uuid4

from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from test_booking import NOW, quote
from test_discovery import published
from test_services import account

from alembic import command
from app import booking_service, business_time, sweep
from app.db import get_engine
from app.models import CancellationPolicy, Reservation


def test_upgrade_backfills_completion_and_missing_policy_without_money_changes(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(business_time, "now", lambda: NOW)
    with Session(get_engine()) as db:
        host, lid = published(db)
        guest, _ = account(db)
        r = booking_service.pay(db, guest, quote(db, lid), str(uuid4())).reservation
        monkeypatch.setattr(
            business_time, "now", lambda: r.scheduled_check_out + timedelta(days=1)
        )
        sweep._one(db, r.id, lid)
        with db.begin():
            row = db.get(Reservation, r.id)
            assert row is not None and row.completed_at == r.scheduled_check_out
            before = (
                row.total_minor,
                row.host_entitlement_minor,
                row.platform_entitlement_minor,
                row.financial_version,
            )
            strict = db.scalar(
                select(CancellationPolicy).where(CancellationPolicy.name == "Strict")
            )
            assert strict is not None
            db.delete(strict)
    config = Config("alembic.ini")
    try:
        command.downgrade(config, "0007_listing_location")
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        with Session(get_engine()) as db:
            row = db.get(Reservation, r.id)
            assert row is not None and row.state == "completed"
            assert row.completed_at == r.scheduled_check_out
            assert before == (
                row.total_minor,
                row.host_entitlement_minor,
                row.platform_entitlement_minor,
                row.financial_version,
            )
            assert set(db.scalars(select(CancellationPolicy.name))) == {
                "Flexible",
                "Moderate",
                "Firm",
                "Strict",
            }
            assert (
                db.scalar(text("SELECT version_num FROM alembic_version"))
                == "0008_communication"
            )
    finally:
        command.upgrade(config, "head")
