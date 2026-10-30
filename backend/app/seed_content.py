"""Explicit manifest-only content import. No downloads, resets or startup hooks."""

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from PIL import Image
from pydantic import Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import auth_service, business_time, listing_service, storage
from app.auth_service import AccessContext
from app.config import get_settings
from app.db import get_engine
from app.errors import ApiError
from app.listing_schemas import DraftFields, ListingPatch, UploadIntentInput
from app.models import (
    CancellationPolicy,
    DemoAssetPhoto,
    DemoImport,
    Listing,
    ListingPhoto,
    now,
)
from app.schemas import LoginInput, StrictModel


class Asset(StrictModel):
    id: str = Field(min_length=1, max_length=100)
    file: str
    source_page: str
    image_url: str
    creator: str
    license: str
    license_url: str
    attribution: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    bytes: int = Field(ge=1, le=10485760)


class DemoListing(DraftFields):
    demo_key: str = Field(min_length=1, max_length=100)
    policy_name: Literal["Flexible", "Moderate", "Firm", "Strict"]
    asset_ids: list[str] = Field(min_length=5, max_length=20)


class Manifest(StrictModel):
    schema_version: Literal[1]
    assets: list[Asset]
    listings: list[DemoListing]


def stable_listing_id(demo_key: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"stayhub:demo:{demo_key}")


def _read_asset(manifest: Path, asset: Asset) -> tuple[bytes, str]:
    path = (manifest.parent / asset.file).resolve()
    if not path.is_relative_to(manifest.parent.resolve()):
        raise ValueError("Asset path escapes the manifest directory")
    if path.stat().st_size != asset.bytes or asset.bytes > storage.MAX_SOURCE_BYTES:
        raise ValueError("Asset size differs from licensed manifest")
    with path.open("rb") as source:
        content = source.read(storage.MAX_SOURCE_BYTES + 1)
    if hashlib.sha256(content).hexdigest() != asset.sha256:
        raise ValueError("Asset checksum differs from licensed manifest")
    with Image.open(path) as image:
        content_type = {
            "JPEG": "image/jpeg",
            "PNG": "image/png",
            "WEBP": "image/webp",
        }.get(image.format or "")
    if not content_type:
        raise ValueError("Asset is not a supported photo format")
    return content, content_type


def _marker(db: Session, actor: AccessContext, demo_key: str) -> DemoImport | None:
    # Return detached marker values, never an open caller transaction.
    with db.begin():
        row = db.get(DemoImport, demo_key)
        if row:
            db.expunge(row)
    return row


def _record_version(db: Session, demo_key: str, before: int, after: int) -> None:
    if after not in {before, before + 1}:
        raise ValueError(
            "Concurrent listing changes detected; preserving partial import"
        )
    with db.begin():
        marker = db.scalar(
            select(DemoImport).where(DemoImport.demo_key == demo_key).with_for_update()
        )
        if marker is None or marker.expected_version != before:
            raise ValueError(
                "Import marker changed concurrently; retry without resetting content"
            )
        marker.expected_version = after


def _ensure_listing(
    db: Session, actor: AccessContext, specification: DemoListing
) -> DemoImport:
    marker = _marker(db, actor, specification.demo_key)
    if marker:
        return marker
    listing_id = stable_listing_id(specification.demo_key)
    with db.begin():
        existing = db.get(Listing, listing_id)
        if existing and (
            existing.owner_id != actor.user_id
            or existing.version != 1
            or existing.title is not None
            or existing.status != "draft"
            or existing.photos
        ):
            raise ValueError(
                "Stable demo identity already has unmarked content; preserving it"
            )
        exists = existing is not None
    if not exists:
        listing_service.create_listing(db, actor, listing_id=listing_id)
    with db.begin():
        marker = DemoImport(
            demo_key=specification.demo_key,
            listing_id=listing_id,
            expected_version=1,
            completed=False,
        )
        db.add(marker)
        db.flush()
        db.expunge(marker)
    return marker


def _import_one(
    db: Session,
    actor: AccessContext,
    specification: DemoListing,
    assets: dict[str, Asset],
    manifest_path: Path,
) -> dict[str, Any]:
    marker = _ensure_listing(db, actor, specification)
    saved = listing_service.get_listing(db, actor, marker.listing_id).listing
    if marker.completed:
        return {
            "demo_key": marker.demo_key,
            "listing_id": str(saved.id),
            "status": "preserved",
            "photo_ids": [str(photo.id) for photo in saved.photos],
        }
    if saved.version != marker.expected_version:
        raise ValueError(
            "Incomplete demo has newer host edits or ambiguous interrupted writes; preserving it"
        )
    if marker.expected_version == 1:
        with db.begin():
            policy = db.scalar(
                select(CancellationPolicy).where(
                    CancellationPolicy.name == specification.policy_name,
                    CancellationPolicy.version == 1,
                )
            )
            if not policy:
                raise ValueError(
                    "Run explicit seed-demo to provision cancellation policies first"
                )
            policy_id = policy.id
        fields = specification.model_dump(
            exclude={"demo_key", "policy_name", "asset_ids", "policy_id"}
        )
        updated = listing_service.update_listing(
            db,
            actor,
            saved.id,
            ListingPatch(version=saved.version, **fields, policy_id=policy_id),
        ).listing
        _record_version(db, marker.demo_key, saved.version, updated.version)
        saved = updated
    missing = []
    for asset_id in specification.asset_ids:
        current_marker = _marker(db, actor, marker.demo_key)
        assert current_marker is not None
        saved = listing_service.get_listing(db, actor, saved.id).listing
        if saved.version != current_marker.expected_version:
            raise ValueError(
                "Host edits detected during partial import; preserving them"
            )
        with db.begin():
            mapping = db.get(DemoAssetPhoto, (marker.demo_key, asset_id))
            photo_id = mapping.photo_id if mapping else None
            photo = db.get(ListingPhoto, photo_id) if photo_id else None
            verified = photo is not None and photo.state == "verified"
            pending = photo is not None and photo.state == "pending"
            expired = (
                photo is not None
                and photo.state in {"pending", "expired"}
                and photo.expires_at <= now()
            )
            expired_state = photo.state if photo is not None else None
        if verified:
            continue
        asset = assets.get(asset_id)
        if not asset:
            missing.append(asset_id)
            continue
        try:
            content, content_type = _read_asset(manifest_path, asset)
        except (OSError, ValueError):
            missing.append(asset_id)
            continue
        if expired and photo_id is not None:
            if expired_state == "pending":
                removed = listing_service.delete_photo(
                    db, actor, saved.id, photo_id
                ).listing
                _record_version(db, marker.demo_key, saved.version, removed.version)
                saved = removed
            with db.begin():
                stale_mapping = db.get(DemoAssetPhoto, (marker.demo_key, asset_id))
                if stale_mapping:
                    db.delete(stale_mapping)
            photo_id, pending = None, False
        if not pending:
            if photo_id:
                raise ValueError(
                    "Mapped photo was removed or expired; preserving host changes"
                )
            intent = listing_service.create_upload_intent(
                db,
                actor,
                saved.id,
                UploadIntentInput(content_type=content_type, bytes=len(content)),
            )
            with db.begin():
                db.add(
                    DemoAssetPhoto(
                        demo_key=marker.demo_key,
                        asset_id=asset_id,
                        photo_id=intent.photo_id,
                    )
                )
            after = listing_service.get_listing(db, actor, saved.id).listing
            _record_version(db, marker.demo_key, saved.version, after.version)
            saved, photo_id = after, intent.photo_id
        assert photo_id is not None
        with db.begin():
            photo = db.get(ListingPhoto, photo_id)
            assert photo is not None
            key = photo.staging_key
        with storage.storage_errors():
            storage.s3_client().put_object(
                Bucket=get_settings().s3_bucket,
                Key=key,
                Body=content,
                ContentType=content_type,
                ContentLength=len(content),
            )
        completed = listing_service.complete_photo(db, actor, saved.id, photo_id)
        _record_version(db, marker.demo_key, saved.version, completed.listing.version)
        saved = completed.listing
    if missing:
        return {
            "demo_key": marker.demo_key,
            "listing_id": str(saved.id),
            "status": "incomplete",
            "missing_asset_ids": missing,
            "photo_ids": [str(photo.id) for photo in saved.photos],
        }
    published = listing_service.publish(db, actor, saved.id, saved.version).listing
    with db.begin():
        stored = db.get(DemoImport, marker.demo_key)
        assert stored is not None
        stored.expected_version = published.version
        stored.completed = True
    return {
        "demo_key": marker.demo_key,
        "listing_id": str(saved.id),
        "status": "imported",
        "photo_ids": [str(photo.id) for photo in published.photos],
    }


def import_manifest(
    db: Session, actor: AccessContext, manifest_path: Path
) -> list[dict[str, Any]]:
    if manifest_path.stat().st_size > 1024 * 1024:
        raise ValueError("Manifest exceeds 1 MiB")
    manifest = Manifest.model_validate_json(manifest_path.read_text())
    assets = {asset.id: asset for asset in manifest.assets}
    if len(assets) != len(manifest.assets) or len(
        {row.demo_key for row in manifest.listings}
    ) != len(manifest.listings):
        raise ValueError("Manifest identifiers must be unique")
    results = []
    for specification in manifest.listings:
        if len(set(specification.asset_ids)) != len(specification.asset_ids):
            raise ValueError("Each listing must identify unique asset slots")
        try:
            results.append(_import_one(db, actor, specification, assets, manifest_path))
        except (ApiError, ValueError):
            results.append(
                {
                    "demo_key": specification.demo_key,
                    "listing_id": str(stable_listing_id(specification.demo_key)),
                    "status": "incomplete_preserved",
                    "message": "Import could not safely continue; check missing assets, storage, expired uploads or newer host edits. No content was reset.",
                }
            )
    return results


def main() -> None:
    path = Path(os.environ["DEMO_CONTENT_MANIFEST"])
    # Session-level advisory lock prevents concurrent explicit import commands.
    with get_engine().connect() as lock:
        acquired = lock.scalar(text("SELECT pg_try_advisory_lock(731342904481)"))
        lock.commit()
        if not acquired:
            raise SystemExit("Another content import is already running; retry later.")
        try:
            with Session(get_engine()) as db:
                issue = auth_service.login(
                    db,
                    LoginInput(
                        email=os.environ["SEED_HOST_EMAIL"],
                        password=os.environ["SEED_HOST_PASSWORD"],
                    ),
                )
                actor = auth_service.access_context(f"Bearer {issue.body.access_token}")
                results = import_manifest(db, actor, path)
                auth_service.logout(db, issue.refresh_token, issue.body.csrf_token)
            from datetime import timedelta

            start = business_time.now().date() + timedelta(days=14)
            print(
                json.dumps(
                    {
                        "results": results,
                        "search_example": {
                            "check_in": str(start),
                            "check_out": str(start + timedelta(days=5)),
                            "guests": 2,
                        },
                    },
                    indent=2,
                )
            )
            if any(row["status"].startswith("incomplete") for row in results):
                raise SystemExit(1)
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(731342904481)"))
            lock.commit()


if __name__ == "__main__":
    try:
        main()
    except (KeyError, OSError, ValueError, ApiError):
        raise SystemExit(
            "Content import configuration/assets are unavailable or invalid; no credentials are displayed."
        ) from None
