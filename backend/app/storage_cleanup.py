"""Conservative scoped cleanup; defaults to dry-run and never removes buckets."""

import argparse
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_engine
from app.message_models import MessageAttachment
from app.models import Listing, ListingPhoto, Reservation, now
from app.storage import PREFIX, delete_object_best_effort, s3_client, storage_errors


def _message_cleanup(
    db: Session, current: datetime, apply: bool, counts: dict[str, int]
) -> None:
    # Finish the preceding read-only listing scan before taking message locks.
    db.rollback()
    reservation_ids = list(
        db.scalars(select(MessageAttachment.reservation_id).distinct())
    )
    for reservation_id in reservation_ids:
        # Completion and sending both lock reservation before attachment.
        db.execute(
            select(Reservation.id)
            .where(Reservation.id == reservation_id)
            .with_for_update()
        )
        attachments = list(
            db.scalars(
                select(MessageAttachment)
                .where(MessageAttachment.reservation_id == reservation_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        for attachment in attachments:
            if attachment.expires_at > current:
                continue
            # The 5-minute upload authorization has expired before this slot's
            # 30-minute expiry. Even sent photos no longer need original bytes.
            counts["staging_objects"] += 1
            source_removed = True
            if apply:
                source_removed = delete_object_best_effort(attachment.source_key)
                if not source_removed:
                    counts["delete_backlog"] += 1
            if attachment.message_id is not None:
                continue  # Verified sent photos are permanent references.
            counts["expired_slots"] += 1
            final_removed = True
            if attachment.final_key:
                counts["orphan_objects"] += 1
                if apply:
                    final_removed = delete_object_best_effort(attachment.final_key)
                    if final_removed:
                        attachment.final_key = None
                    else:
                        counts["delete_backlog"] += 1
            if apply and source_removed and final_removed:
                db.delete(attachment)
        if apply:
            db.commit()
        else:
            db.rollback()

    # A completion writes its pixel-only object before DB commit. Preserve the
    # same 24h rollback-orphan grace as listing photos, then check references
    # afresh under the reservation/attachment locks instead of a stale snapshot.
    paginator = s3_client().get_paginator("list_objects_v2")
    with storage_errors():
        for page in paginator.paginate(
            Bucket=get_settings().s3_bucket, Prefix=f"{PREFIX}messages/verified/"
        ):
            for item in page.get("Contents", []):
                key, modified = item.get("Key"), item.get("LastModified")
                if not key or not modified or modified > current - timedelta(hours=24):
                    continue
                segments = key.split("/")
                if len(segments) != 5:
                    continue
                try:
                    attachment_id = UUID(segments[3])
                    UUID(segments[4])
                except ValueError:
                    continue
                candidate_reservation_id = db.scalar(
                    select(MessageAttachment.reservation_id).where(
                        MessageAttachment.id == attachment_id
                    )
                )
                if candidate_reservation_id is not None:
                    db.execute(
                        select(Reservation.id)
                        .where(Reservation.id == candidate_reservation_id)
                        .with_for_update()
                    )
                    referenced_attachment = db.scalar(
                        select(MessageAttachment)
                        .where(MessageAttachment.id == attachment_id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                    if (
                        referenced_attachment is not None
                        and referenced_attachment.final_key == key
                    ):
                        db.rollback()
                        continue
                counts["orphan_objects"] += 1
                if apply and not delete_object_best_effort(key):
                    counts["delete_backlog"] += 1
                db.rollback()


def cleanup(apply: bool = False) -> dict[str, int]:
    counts = {
        "expired_slots": 0,
        "staging_objects": 0,
        "orphan_objects": 0,
        "delete_backlog": 0,
    }
    current = now()
    with Session(get_engine()) as db:
        # Lock in the same order as completion: listing then photo. Completion
        # cannot race expiry cleanup while validating/re-encoding externally.
        ids = list(db.scalars(select(Listing.id).order_by(Listing.id)))
        for listing_id in ids:
            listing = db.scalar(
                select(Listing).where(Listing.id == listing_id).with_for_update()
            )
            if listing is None:
                continue
            photos = list(
                db.scalars(
                    select(ListingPhoto).where(ListingPhoto.listing_id == listing_id)
                )
            )
            for photo in photos:
                expired = photo.expires_at <= current
                if photo.state == "pending" and expired:
                    counts["expired_slots"] += 1
                    if apply:
                        photo.state = "expired"
                # Staging auth may remain reusable until its expiry even after
                # verification/removal; don't delete active upload objects early.
                if expired:
                    counts["staging_objects"] += 1
                    if apply and not delete_object_best_effort(photo.staging_key):
                        counts["delete_backlog"] += 1
            if apply:
                db.commit()
            else:
                db.rollback()
        # Final keys are generated only while holding a listing lock. Retain a
        # 24h grace period so a precommit upload is never collected as an orphan.
        references = set(
            db.scalars(
                select(ListingPhoto.final_key).where(
                    ListingPhoto.state == "verified",
                    ListingPhoto.final_key.is_not(None),
                )
            )
        )
        paginator = s3_client().get_paginator("list_objects_v2")
        with storage_errors():
            for page in paginator.paginate(
                Bucket=get_settings().s3_bucket, Prefix=f"{PREFIX}final/"
            ):
                for item in page.get("Contents", []):
                    key = item.get("Key")
                    modified = item.get("LastModified")
                    if (
                        not key
                        or not modified
                        or key in references
                        or modified > current - timedelta(hours=24)
                    ):
                        continue
                    # Avoid TOCTOU with an unusually long completion transaction.
                    # UUID listing segment is server-generated, parsed from key.
                    segments = key.split("/")
                    if len(segments) != 5:
                        continue
                    try:
                        listing_id = UUID(segments[3])
                    except ValueError:
                        continue
                    db.execute(
                        select(Listing.id)
                        .where(Listing.id == listing_id)
                        .with_for_update()
                    )
                    referenced = db.scalar(
                        select(ListingPhoto.id).where(
                            ListingPhoto.final_key == key,
                            ListingPhoto.state == "verified",
                        )
                    )
                    if referenced:
                        db.rollback()
                        continue
                    counts["orphan_objects"] += 1
                    if apply and not delete_object_best_effort(key):
                        counts["delete_backlog"] += 1
                    db.rollback()
        _message_cleanup(db, current, apply, counts)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run", action="store_true", help="Report only (the default)"
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Remove only scoped expired staging and old unreferenced final objects",
    )
    args = parser.parse_args()
    counts = cleanup(apply=args.apply)
    print(
        "Applied scoped cleanup:" if args.apply else "Dry-run scoped cleanup:", counts
    )


if __name__ == "__main__":
    main()
