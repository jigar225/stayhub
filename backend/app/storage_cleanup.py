"""Conservative scoped cleanup; defaults to dry-run and never removes buckets."""

import argparse
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_engine
from app.models import Listing, ListingPhoto, now
from app.storage import PREFIX, delete_object_best_effort, s3_client, storage_errors


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
                    from uuid import UUID

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
