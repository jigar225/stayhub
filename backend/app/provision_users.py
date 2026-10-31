"""Explicit, one-time bulk provisioning of realistic users, hosts and listings.

Reads a JSON specification, creates accounts and (optionally) published listings
with real S3 photos through the existing listing service. Idempotent: stable
UUIDs and demo markers mean re-runs never duplicate or reset existing content.

Creates no accounts on import, on application startup or during deployment.
Operator-invoked only. Credentials are written to a root-only file and are never
printed to stdout, logs or process arguments.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from PIL import Image
from pydantic import EmailStr, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import listing_service, storage
from app.auth_service import AccessContext
from app.config import get_settings
from app.db import get_engine
from app.errors import ApiError
from app.listing_schemas import DraftFields, ListingPatch, UploadIntentInput
from app.models import (
    AuthSession,
    CancellationPolicy,
    DemoAssetPhoto,
    DemoImport,
    ListingPhoto,
    User,
    UserRole,
    now,
)
from app.policies import seed_policies
from app.schemas import StrictModel
from app.security import password_hasher

ADVISORY_LOCK_KEY = 731342904482
CREDENTIALS_FILENAME = "provisioned-credentials.txt"
NAMESPACE = "stayhub:provision"


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


class ProvisionedListing(DraftFields):
    demo_key: str = Field(min_length=1, max_length=100)
    policy_name: Literal["Flexible", "Moderate", "Firm", "Strict"]
    asset_ids: list[str] = Field(min_length=5, max_length=20)


class ProvisionedUser(StrictModel):
    key: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    roles: list[Literal["guest", "host", "admin"]] = Field(min_length=1)
    listings: list[ProvisionedListing] = Field(default_factory=list)


class Manifest(StrictModel):
    schema_version: Literal[1]
    assets: list[Asset]
    users: list[ProvisionedUser]


def _stable(kind: str, key: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"{NAMESPACE}:{kind}:{key}")


def _read_asset(manifest: Path, asset: Asset) -> tuple[bytes, str]:
    path = (manifest.parent / asset.file).resolve()
    if not path.is_relative_to(manifest.parent.resolve()):
        raise ValueError("Asset path escapes the manifest directory")
    if path.stat().st_size != asset.bytes or asset.bytes > storage.MAX_SOURCE_BYTES:
        raise ValueError("Asset size differs from licensed manifest")
    content = path.read_bytes()
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


def _ensure_user(db: Session, specification: ProvisionedUser) -> tuple[User, str, bool]:
    """Create the account if absent. Returns (user, plaintext_password, created)."""
    email = str(specification.email)
    roles = sorted(set(specification.roles))
    existing = db.scalar(select(User).where(User.email == email).with_for_update())
    if existing is not None:
        if {row.role for row in existing.memberships} != set(roles):
            raise ValueError(
                f"Existing account {email} has different roles; nothing was changed"
            )
        return existing, "", False
    password = secrets.token_urlsafe(18)
    user = User(
        id=_stable("user", specification.key),
        email=email,
        name=specification.name,
        password_hash=password_hasher.hash(password),
        memberships=[UserRole(role=role) for role in roles],
    )
    db.add(user)
    db.flush()
    return user, password, True


def _policy_id(db: Session, name: str) -> UUID:
    with db.begin():
        policy = db.scalar(
            select(CancellationPolicy).where(
                CancellationPolicy.name == name,
                CancellationPolicy.version == 1,
            )
        )
        if policy is None:
            raise ValueError("Cancellation policies must be seeded first")
        return policy.id


def _import_listing(
    db: Session,
    actor: AccessContext,
    specification: ProvisionedListing,
    assets: dict[str, Asset],
    manifest_path: Path,
) -> dict[str, Any]:
    listing_id = _stable("listing", specification.demo_key)
    with db.begin():
        marker = db.get(DemoImport, specification.demo_key)
        completed = marker.completed if marker is not None else None
    if completed:
        return {
            "demo_key": specification.demo_key,
            "listing_id": str(listing_id),
            "status": "preserved",
        }
    policy_id = _policy_id(db, specification.policy_name)
    if completed is None:
        listing_service.create_listing(db, actor, listing_id=listing_id)
        with db.begin():
            db.add(
                DemoImport(
                    demo_key=specification.demo_key,
                    listing_id=listing_id,
                    expected_version=1,
                    completed=False,
                )
            )
    saved = listing_service.get_listing(db, actor, listing_id).listing
    if saved.version == 1:
        fields = specification.model_dump(
            exclude={"demo_key", "policy_name", "asset_ids", "policy_id"}
        )
        saved = listing_service.update_listing(
            db,
            actor,
            listing_id,
            ListingPatch(version=saved.version, **fields, policy_id=policy_id),
        ).listing
    for asset_id in specification.asset_ids:
        saved = listing_service.get_listing(db, actor, listing_id).listing
        with db.begin():
            existing_mapping = db.get(
                DemoAssetPhoto, (specification.demo_key, asset_id)
            )
            photo_id = existing_mapping.photo_id if existing_mapping else None
        if photo_id is not None:
            continue
        asset = assets.get(asset_id)
        if asset is None:
            raise ValueError(f"Unknown asset id {asset_id}")
        content, content_type = _read_asset(manifest_path, asset)
        intent = listing_service.create_upload_intent(
            db,
            actor,
            listing_id,
            UploadIntentInput(content_type=content_type, bytes=len(content)),
        )
        with db.begin():
            photo = db.get(ListingPhoto, intent.photo_id)
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
        with db.begin():
            db.add(
                DemoAssetPhoto(
                    demo_key=specification.demo_key,
                    asset_id=asset_id,
                    photo_id=intent.photo_id,
                )
            )
        listing_service.complete_photo(db, actor, listing_id, intent.photo_id)
    saved = listing_service.get_listing(db, actor, listing_id).listing
    if saved.status != "published":
        saved = listing_service.publish(db, actor, listing_id, saved.version).listing
    with db.begin():
        stored = db.get(DemoImport, specification.demo_key)
        assert stored is not None
        stored.expected_version = saved.version
        stored.completed = True
    return {
        "demo_key": specification.demo_key,
        "listing_id": str(listing_id),
        "status": "imported",
    }


def provision(
    db: Session, manifest_path: Path, credentials_path: Path
) -> list[dict[str, Any]]:
    if manifest_path.stat().st_size > 1024 * 1024:
        raise ValueError("Manifest exceeds 1 MiB")
    manifest = Manifest.model_validate_json(manifest_path.read_text())
    assets = {asset.id: asset for asset in manifest.assets}
    if len(assets) != len(manifest.assets):
        raise ValueError("Asset identifiers must be unique")
    if len({row.key for row in manifest.users}) != len(manifest.users):
        raise ValueError("User keys must be unique")
    if len({str(row.email) for row in manifest.users}) != len(manifest.users):
        raise ValueError("User emails must be unique")
    demo_keys = [
        listing.demo_key for user in manifest.users for listing in user.listings
    ]
    if len(set(demo_keys)) != len(demo_keys):
        raise ValueError("Listing demo keys must be unique")

    with db.begin():
        seed_policies(db)

    results: list[dict[str, Any]] = []
    credentials: list[str] = []
    for specification in manifest.users:
        with db.begin():
            user, password, created = _ensure_user(db, specification)
            user_id = user.id
            actor_roles = sorted({row.role for row in user.memberships})
            session_id = db.scalar(
                select(AuthSession.id).where(
                    AuthSession.user_id == user_id,
                    AuthSession.revoked_at.is_(None),
                    AuthSession.expires_at > now(),
                )
            )
            if session_id is None:
                session = AuthSession(
                    id=uuid4(),
                    user_id=user_id,
                    expires_at=now() + timedelta(days=1),
                    csrf_hash="0" * 64,
                )
                db.add(session)
                db.flush()
                session_id = session.id
        if "host" in actor_roles:
            actor = _actor_for(user_id, session_id)
            for listing in specification.listings:
                try:
                    outcome = _import_listing(db, actor, listing, assets, manifest_path)
                except (ApiError, ValueError) as error:
                    outcome = {
                        "demo_key": listing.demo_key,
                        "status": "failed",
                        "message": str(error),
                    }
                outcome["host"] = str(specification.email)
                results.append(outcome)
        elif specification.listings:
            raise ValueError(
                f"User {specification.email} declares listings but lacks the host role"
            )
        if created:
            credentials.append(
                f"{specification.email},{password},{','.join(actor_roles)}"
            )

    _write_credentials(credentials_path, credentials)
    return results


def _actor_for(user_id: UUID, session_id: UUID) -> AccessContext:
    """Build an access context bound to a real provisioning session row.

    The listing service re-reads and validates live session/role state on every
    call, so the session must exist in the database.
    """
    return AccessContext(
        user_id=user_id, session_id=session_id, expires_at=now() + timedelta(days=1)
    )


def _write_credentials(path: Path, rows: list[str]) -> None:
    if not rows:
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(
            "# Generated by app.provision_users. Keep private. One-time output.\n"
        )
        stream.write("email,password,roles\n")
        stream.write("\n".join(rows))
        stream.write("\n")


def main() -> None:
    manifest_path = Path(os.environ["PROVISION_MANIFEST"])
    credentials_path = Path(
        os.environ.get(
            "PROVISION_CREDENTIALS",
            f"/opt/stayhub/{CREDENTIALS_FILENAME}",
        )
    )
    with get_engine().connect() as lock:
        acquired = lock.scalar(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": ADVISORY_LOCK_KEY}
        )
        lock.commit()
        if not acquired:
            raise SystemExit("Another provisioning run is active; retry later.")
        try:
            with Session(get_engine()) as db:
                results = provision(db, manifest_path, credentials_path)
            print(
                json.dumps(
                    {
                        "users": len({row["host"] for row in results}),
                        "listings": len(results),
                        "results": results,
                    },
                    indent=2,
                )
            )
            if any(row["status"] == "failed" for row in results):
                raise SystemExit(1)
        finally:
            lock.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": ADVISORY_LOCK_KEY}
            )
            lock.commit()


if __name__ == "__main__":
    try:
        main()
    except (KeyError, OSError, ValueError, ApiError) as error:
        # Exception messages never contain generated passwords (those are only
        # ever written to the private credentials file).
        print(
            f"Provisioning failed: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        raise SystemExit(
            "Provisioning is misconfigured or assets are unavailable; "
            "no credentials are displayed."
        ) from None
