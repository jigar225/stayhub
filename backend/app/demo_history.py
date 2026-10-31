"""Explicit demo-only historical import. Dry-run by default; never run on startup.

Historical reservations are imported with current listing/policy snapshots, then
normal lifecycle and review services reconcile them. All five stays commit in one
transaction. Stable IDs prevent retries from duplicating or resetting user work.
"""

from __future__ import annotations

import argparse
import json
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app import booking_ledger, business_time, pricing, review_service, sweep
from app.auth_service import AccessContext
from app.date_rules import local_today, scheduled
from app.db import get_engine
from app.models import (
    AuthSession,
    CalendarEntry,
    CancellationPolicy,
    Listing,
    Payment,
    Payout,
    Reservation,
    User,
    now,
)
from app.review_models import Review
from app.review_schemas import CATEGORIES, ReviewInput

BATCH = "stayhub:review-demo:v1"


def run(
    engine: Engine, host_email: str, guests: list[str], *, apply: bool = False
) -> dict[str, Any]:
    if len(guests) != 5 or len(set(guests)) != 5 or host_email in guests:
        raise ValueError(
            "Exactly five distinct guests and a separate host are required"
        )
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text("SELECT pg_advisory_xact_lock(731342904483)"))
            with Session(
                connection,
                join_transaction_mode="create_savepoint",
                expire_on_commit=False,
            ) as db:
                with db.begin():
                    host = db.scalar(
                        select(User).where(User.email == host_email, User.active)
                    )
                    assert host and any(m.role == "host" for m in host.memberships), (
                        "Active host missing"
                    )
                    ids = [uuid5(NAMESPACE_URL, f"{BATCH}:{i}") for i in range(5)]
                    existing = [db.get(Reservation, rid) for rid in ids]
                    assert all(existing) or not any(existing), (
                        "Partial import detected; inspect before retry"
                    )
                    listing = (
                        db.get(Listing, existing[0].listing_id)
                        if existing[0]
                        else db.scalar(
                            select(Listing)
                            .where(
                                Listing.owner_id == host.id,
                                Listing.status == "published",
                            )
                            .order_by(Listing.id)
                            .with_for_update()
                        )
                    )
                    assert listing and listing.owner_id == host.id and listing.timezone
                    moment = business_time.at(db)
                    today = local_today(listing.timezone, moment)
                    policy = db.get(CancellationPolicy, listing.policy_id)
                    assert policy
                    rows = []
                    for i, email in enumerate(guests):
                        guest = db.scalar(
                            select(User).where(User.email == email, User.active)
                        )
                        assert guest and any(
                            m.role == "guest" for m in guest.memberships
                        )
                        assert not any(m.role == "admin" for m in guest.memberships)
                        if existing[i]:
                            row = existing[i]
                            assert (
                                row
                                and row.guest_id == guest.id
                                and row.host_id == host.id
                            )
                            rows.append(row)
                            continue
                        checkout = today - timedelta(days=10 - i * 2)
                        checkin = checkout - timedelta(days=1)
                        assert not pricing.occupancy_exists(
                            db, listing.id, checkin, checkout
                        ), "Demo dates overlap existing occupancy; nothing imported"
                        amounts = pricing.price(listing, checkin, checkout)
                        fee = (amounts.subtotal_minor * 3 + 50) // 100
                        arrival = scheduled(
                            checkin, listing.check_in_time or "15:00", listing.timezone
                        )
                        departure = scheduled(
                            checkout,
                            listing.check_out_time or "11:00",
                            listing.timezone,
                        )
                        created = arrival - timedelta(days=3)
                        row = Reservation(
                            id=ids[i],
                            code="SH-DEMO-" + ids[i].hex[:12].upper(),
                            listing_id=listing.id,
                            guest_id=guest.id,
                            host_id=host.id,
                            state="confirmed",
                            booking_mode=listing.booking_mode,
                            check_in=checkin,
                            check_out=checkout,
                            guests=1,
                            timezone=listing.timezone,
                            scheduled_check_in=arrival,
                            scheduled_check_out=departure,
                            created_at=created,
                            request_deadline=created + timedelta(hours=24)
                            if listing.booking_mode == "request"
                            else None,
                            listing_snapshot={
                                "title": listing.title,
                                "destination": listing.destination,
                                "property_type": listing.property_type,
                                "description": listing.description,
                                "amenities": listing.amenities or [],
                                "house_rules": listing.house_rules or [],
                                "host_name": host.name,
                            },
                            policy_snapshot={
                                **pricing.policy(db, listing).model_dump(mode="json"),
                                "definition": policy.definition,
                            },
                            **amounts.model_dump(exclude={"nights", "currency"}),
                            host_fee_minor=fee,
                            effective_host_fee_minor=fee,
                            financial_version=1,
                            host_entitlement_minor=amounts.subtotal_minor - fee,
                            platform_entitlement_minor=amounts.guest_fee_minor + fee,
                        )
                        db.add(row)
                        db.flush()
                        payment = Payment(
                            reservation_id=row.id,
                            operation_id=f"charge:{row.id}",
                            amount_minor=row.total_minor,
                            currency="EUR",
                            paid_at=created,
                        )
                        db.add_all(
                            [
                                payment,
                                Payout(
                                    reservation_id=row.id,
                                    host_id=host.id,
                                    due_at=arrival + timedelta(hours=24),
                                    gross_minor=row.subtotal_minor,
                                    host_fee_minor=fee,
                                    net_minor=row.host_entitlement_minor,
                                    status="scheduled",
                                ),
                                CalendarEntry(
                                    listing_id=listing.id,
                                    kind="reservation",
                                    reservation_id=row.id,
                                    check_in=checkin,
                                    check_out=checkout,
                                    active=True,
                                ),
                            ]
                        )
                        db.flush()
                        initial = (
                            "pending"
                            if listing.booking_mode == "request"
                            else "confirmed"
                        )
                        booking_ledger.event(
                            db,
                            None,
                            "reservation.created",
                            "reservation",
                            row.id,
                            None,
                            {"state": initial, "demo_batch": BATCH},
                            created,
                            system_identity="demo-history-import",
                        )
                        if initial == "pending":
                            booking_ledger.event(
                                db,
                                host.id,
                                "reservation.accepted",
                                "reservation",
                                row.id,
                                {"state": "pending"},
                                {"state": "confirmed", "demo_batch": BATCH},
                                created + timedelta(hours=1),
                            )
                        booking_ledger.event(
                            db,
                            None,
                            "payment.charged",
                            "payment",
                            payment.id,
                            None,
                            {
                                "reservation_id": str(row.id),
                                "amount_minor": row.total_minor,
                                "currency": "EUR",
                                "demo_batch": BATCH,
                            },
                            created,
                            system_identity="demo-history-import",
                        )
                        rows.append(row)
                if not any(existing):
                    for row in rows:
                        sweep._one(db, row.id, row.listing_id)
                    with db.begin():
                        actors = {}
                        for uid in {host.id, *(r.guest_id for r in rows[:3])}:
                            session = AuthSession(
                                id=uuid4(),
                                user_id=uid,
                                expires_at=now() + timedelta(minutes=10),
                                csrf_hash="0" * 64,
                            )
                            db.add(session)
                            actors[uid] = AccessContext(
                                user_id=uid,
                                session_id=session.id,
                                expires_at=session.expires_at,
                            )
                    for i, row in enumerate(rows[:3]):
                        rating = [5, 4, 5][i]
                        review_service.submit(
                            db,
                            actors[row.guest_id],
                            row.id,
                            ReviewInput(
                                text="[Demo review] "
                                + [
                                    "Comfortable rooms, a convenient location and clear check-in instructions.",
                                    "A pleasant stay with a helpful host and a well-equipped kitchen.",
                                    "A clean, welcoming home. We enjoyed the neighbourhood and would return.",
                                ][i],
                                overall=rating,
                                categories=dict.fromkeys(CATEGORIES, rating),
                            ),
                        )
                        review_service.submit(
                            db,
                            actors[host.id],
                            row.id,
                            ReviewInput(
                                text="[Demo review] A considerate guest who communicated clearly and left the home tidy."
                            ),
                        )
                    with db.begin():
                        for actor in actors.values():
                            saved_session = db.get(AuthSession, actor.session_id)
                            assert saved_session
                            saved_session.revoked_at = now()
                report = []
                with db.begin():
                    for row, email in zip(rows, guests, strict=True):
                        db.refresh(row)
                        payout = db.scalar(
                            select(Payout).where(Payout.reservation_id == row.id)
                        )
                        saved_payment = db.scalar(
                            select(Payment).where(Payment.reservation_id == row.id)
                        )
                        assert (
                            row.state == "completed"
                            and payout
                            and payout.status == "paid"
                            and saved_payment
                        )
                        assert (
                            saved_payment.amount_minor
                            == row.total_minor
                            == payout.net_minor + row.platform_entitlement_minor
                        )
                        reviews = list(
                            db.scalars(
                                select(Review).where(Review.reservation_id == row.id)
                            )
                        )
                        report.append(
                            {
                                "guest": email,
                                "code": row.code,
                                "reservation_id": str(row.id),
                                "checkout": str(row.check_out),
                                "review_deadline": str(
                                    row.completed_at + timedelta(days=14)
                                )
                                if row.completed_at
                                else None,
                                "reviews": len(reviews),
                                "published": sum(
                                    r.published_at is not None for r in reviews
                                ),
                                "charged_minor": saved_payment.amount_minor,
                                "paid_minor": payout.net_minor,
                            }
                        )
                result = {
                    "mode": "apply" if apply else "dry-run (rolled back)",
                    "already_imported": bool(any(existing)),
                    "host": host_email,
                    "listing": listing.title,
                    "listing_id": str(listing.id),
                    "stays": report,
                }
            if apply:
                transaction.commit()
            else:
                transaction.rollback()
            return result
        except BaseException:
            transaction.rollback()
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--manifest", default="/demo-content/provision.json")
    args = parser.parse_args()
    users = json.loads(Path(args.manifest).read_text())["users"]
    host = next(u["email"] for u in users if "host" in u["roles"])
    guests = [u["email"] for u in users if u["roles"] == ["guest"]][:5]
    print(json.dumps(run(get_engine(), host, guests, apply=args.apply), indent=2))


if __name__ == "__main__":
    main()
