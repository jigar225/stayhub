"""Chronological per-reservation lifecycle and exactly-once simulated payout sweep."""

import argparse
import json
import logging
import time
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import booking_ledger, business_time
from app.booking_service import _locked_listing
from app.db import get_engine
from app.financial_schemas import SweepResult
from app.models import Payout, Reservation

logger = logging.getLogger(__name__)


def _one(db: Session, rid: UUID, lid: UUID) -> SweepResult:
    result = SweepResult(scanned=1)
    with db.begin():
        _locked_listing(db, lid)
        row = db.scalar(
            select(Reservation)
            .where(Reservation.id == rid)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            return result
        payout = db.scalar(
            select(Payout)
            .where(Payout.reservation_id == rid)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        now = business_time.at(db)
        if row.state == "pending":
            if row.request_deadline is not None and now >= row.request_deadline:
                booking_ledger.decline(
                    db, row, None, "expired", row.request_deadline, expired=True
                )
                result.expired = 1
            return result
        # Repeatedly choose the next effective event; checkout wins a payout tie.
        while True:
            events = []
            if row.state == "confirmed":
                events.append((row.scheduled_check_in, 1, "checked_in"))
            if row.state == "checked_in":
                events.append((row.scheduled_check_out, 2, "completed"))
            if (
                payout is not None
                and payout.status == "scheduled"
                and payout.net_minor > 0
            ):
                events.append((payout.due_at, 3, "paid"))
            due = [event for event in events if event[0] <= now]
            if not due:
                break
            effective, _, action = min(due)
            if action == "paid":
                assert payout is not None
                payout.status = "paid"
                payout.paid_at = effective
                payout.release_operation = f"payout:{row.id}"
                booking_ledger.event(
                    db,
                    None,
                    "payout.paid",
                    "payout",
                    payout.id,
                    {"status": "scheduled"},
                    {
                        "status": "paid",
                        "reservation_id": str(row.id),
                        "amount_minor": payout.net_minor,
                    },
                    effective,
                    system_identity="lifecycle-sweep",
                )
                result.paid += 1
            else:
                previous = row.state
                row.state = action
                row.financial_version += 1
                booking_ledger.event(
                    db,
                    None,
                    f"reservation.{action}",
                    "reservation",
                    row.id,
                    {"state": previous},
                    {"state": action},
                    effective,
                    system_identity="lifecycle-sweep",
                )
                if action == "checked_in":
                    result.checked_in += 1
                else:
                    result.completed += 1
            db.flush()
    return result


def run(db: Session, batch_size: int = 100) -> SweepResult:
    if not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be1–1000")
    with db.begin():
        now = business_time.at(db)
        query = (
            select(Reservation.id, Reservation.listing_id)
            .outerjoin(Payout, Payout.reservation_id == Reservation.id)
            .where(
                or_(
                    (Reservation.state == "pending")
                    & (Reservation.request_deadline <= now),
                    (Reservation.state == "confirmed")
                    & (Reservation.scheduled_check_in <= now),
                    (Reservation.state == "checked_in")
                    & (Reservation.scheduled_check_out <= now),
                    (Payout.status == "scheduled")
                    & (Payout.net_minor > 0)
                    & (Payout.due_at <= now),
                )
            )
            .order_by(Reservation.id)
            .limit(batch_size + 1)
        )
        candidates = list(db.execute(query))
    result = SweepResult(has_more=len(candidates) > batch_size)
    for rid, lid in candidates[:batch_size]:
        try:
            value = _one(db, rid, lid)
            for field in ["scanned", "expired", "checked_in", "completed", "paid"]:
                setattr(result, field, getattr(result, field) + getattr(value, field))
        except SQLAlchemyError:
            result.scanned += 1
            result.deferred += 1
            result.has_more = True
            logger.warning("Sweep deferred reservation %s", rid)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Progress due stays, expire requests and release due simulated payouts."
    )
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=float, default=60)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 1000 or args.interval < 1:
        parser.error("Use batch-size1–1000 and interval>=1")
    while True:
        try:
            with Session(get_engine()) as db:
                result = run(db, args.batch_size)
            print(result.model_dump_json(), flush=True)
            if not args.loop:
                if result.deferred:
                    raise SystemExit(1)
                return
        except SQLAlchemyError:
            if not args.loop:
                raise
            print(
                json.dumps({"status": "waiting_for_database_or_migration"}), flush=True
            )
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
