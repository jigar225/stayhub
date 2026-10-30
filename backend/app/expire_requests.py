"""Bounded, restart-safe request expiry CLI and local periodic worker."""

import argparse
import json
import logging
import time
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import booking_ledger, business_time
from app.booking_service import _locked_listing
from app.db import get_engine
from app.models import Reservation

logger = logging.getLogger(__name__)


def _expire_one(db: Session, reservation_id: UUID, listing_id: UUID) -> bool:
    with db.begin():
        _locked_listing(db, listing_id)
        row = db.scalar(
            select(Reservation)
            .where(Reservation.id == reservation_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        now = business_time.at(db)
        if (
            row is None
            or row.state != "pending"
            or row.request_deadline is None
            or now < row.request_deadline
        ):
            return False
        booking_ledger.decline(db, row, None, "expired", now, expired=True)
    return True


def expire_requests(db: Session, batch_size: int = 100) -> dict[str, int]:
    if not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be 1–1000")
    with db.begin():
        candidates = list(
            db.execute(
                select(Reservation.id, Reservation.listing_id)
                .where(
                    Reservation.state == "pending",
                    Reservation.request_deadline <= business_time.now(),
                )
                .order_by(Reservation.request_deadline, Reservation.id)
                .limit(batch_size)
            )
        )
    expired = 0
    deferred = 0
    for reservation_id, listing_id in candidates:
        try:
            expired += _expire_one(db, reservation_id, listing_id)
        except SQLAlchemyError:
            # The per-request transaction already rolled back. Retry next batch;
            # log only safe identifiers, never DB DSNs or quote/auth credentials.
            logger.warning("Request expiry deferred for reservation %s", reservation_id)
            deferred += 1
    return {"scanned": len(candidates), "expired": expired, "deferred": deferred}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Expire unanswered booking requests using business time."
    )
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=float, default=60)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 1000 or args.interval < 1:
        parser.error("Use batch-size 1–1000 and interval >=1 second.")
    while True:
        try:
            with Session(get_engine()) as db:
                result = expire_requests(db, args.batch_size)
            print(json.dumps(result), flush=True)
        except SQLAlchemyError:
            if not args.loop:
                raise
            # Worker can start before the migration in make dev-up→migrate.
            print(
                json.dumps({"status": "waiting_for_database_or_migration"}), flush=True
            )
        if not args.loop:
            if result["deferred"]:
                raise SystemExit(1)
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
