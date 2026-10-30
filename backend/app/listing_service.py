"""Complete owner listing/photo operations; private helpers never commit."""

from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import storage
from app.auth_service import AccessContext, current_user
from app.errors import ApiError
from app.listing_schemas import (
    CompleteResponse,
    ListingOutput,
    ListingPatch,
    ListingResponse,
    ListingsResponse,
    PhotoOrderInput,
    PhotoOutput,
    PhotoReadResponse,
    PoliciesResponse,
    PolicyOutput,
    UploadAuthorization,
    UploadIntentInput,
    UploadIntentResponse,
)
from app.models import CancellationPolicy, Listing, ListingPhoto, User, now
from app.security import require_role

DRAFT_FIELDS = [
    "property_type",
    "address",
    "destination",
    "timezone",
    "capacity",
    "bedrooms",
    "beds",
    "baths",
    "title",
    "description",
    "amenities",
    "house_rules",
    "nightly_minor",
    "cleaning_minor",
    "policy_id",
    "booking_mode",
    "check_in_time",
    "check_out_time",
]
BANNED_RULES = ("no children", "no foreigners", "no disabled", "adults only")


def _owned_listing(
    db: Session, user: User, listing_id: UUID, lock: bool = False
) -> Listing:
    require_role(user, "host")
    query = (
        select(Listing)
        .where(Listing.id == listing_id, Listing.owner_id == user.id)
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    listing = db.scalar(query)
    if listing is None:
        raise ApiError(404, "not_found", "This listing could not be found.")
    # Relationship loaded after lock, so waiting mutations see committed photos.
    if lock:
        db.refresh(listing, ["photos"])
    return listing


def _verified_photos(listing: Listing) -> list[ListingPhoto]:
    return sorted(
        (photo for photo in listing.photos if photo.state == "verified"),
        key=lambda photo: (photo.order or 0, str(photo.id)),
    )


def _listing_output(listing: Listing) -> ListingOutput:
    fields: dict[str, Any] = {field: getattr(listing, field) for field in DRAFT_FIELDS}
    return ListingOutput(
        **fields,
        id=listing.id,
        status=listing.status,
        version=listing.version,
        created_at=listing.created_at,
        updated_at=listing.updated_at,
        photos=[
            PhotoOutput.model_validate(photo) for photo in _verified_photos(listing)
        ],
    )


def _check_version(listing: Listing, version: int) -> None:
    if listing.version != version:
        raise ApiError(
            409,
            "stale_version",
            "This listing changed elsewhere. Reload its saved version before saving your edits.",
        )


def _bump(listing: Listing) -> None:
    listing.version += 1
    listing.updated_at = now()


def _validate_policy(db: Session, policy_id: UUID | None) -> None:
    if policy_id is not None and db.get(CancellationPolicy, policy_id) is None:
        raise ApiError(
            422,
            "validation_error",
            "Choose an available cancellation policy.",
            field_errors={"policy_id": "Choose an available cancellation policy."},
        )


def _publication_errors(listing: Listing) -> dict[str, str]:
    errors = {
        field: "This field is required to publish."
        for field in DRAFT_FIELDS
        if getattr(listing, field) is None
    }
    for rule in listing.house_rules or []:
        normalized = " ".join(rule.casefold().split())
        if any(phrase in normalized for phrase in BANNED_RULES):
            errors["house_rules"] = (
                "Remove discriminatory custom rules before publishing."
            )
    if len(_verified_photos(listing)) < 5:
        errors["photos"] = "Upload and verify at least five photos before publishing."
    return errors


def _require_publishable(listing: Listing) -> None:
    errors = _publication_errors(listing)
    if errors:
        raise ApiError(
            422,
            "publication_invalid",
            "Complete the required fields and photos before publishing.",
            field_errors=errors,
        )


def _own_photo(listing: Listing, photo_id: UUID) -> ListingPhoto:
    photo = next(
        (
            item
            for item in listing.photos
            if item.id == photo_id and item.state not in {"deleted", "expired"}
        ),
        None,
    )
    if photo is None:
        raise ApiError(404, "not_found", "This photo could not be found.")
    return photo


def _create_upload(
    db: Session, listing: Listing, content_type: str, size: int
) -> tuple[ListingPhoto, str]:
    active = [
        photo
        for photo in listing.photos
        if photo.state == "verified"
        or (photo.state == "pending" and photo.expires_at > now())
    ]
    if len(active) >= 20:
        raise ApiError(
            409,
            "photo_limit",
            "A listing can have at most 20 photos and active uploads. Remove a photo or wait for unused uploads to expire.",
        )
    photo_id = uuid4()
    key = (
        f"{storage.PREFIX}staging/{listing.owner_id}/{listing.id}/{photo_id}/{uuid4()}"
    )
    url = storage.upload_url(key, content_type, size)
    photo = ListingPhoto(
        id=photo_id,
        listing_id=listing.id,
        content_type=content_type,
        source_bytes=size,
        staging_key=key,
        expires_at=now() + timedelta(seconds=300),
    )
    listing.photos.append(photo)
    _bump(listing)
    db.flush()
    return photo, url


def _complete_upload(db: Session, listing: Listing, photo: ListingPhoto) -> None:
    if photo.state == "verified":
        return
    if photo.expires_at <= now():
        raise ApiError(
            422,
            "upload_expired",
            "This upload authorization expired. Start a new upload.",
        )
    content = storage.read_source(photo.staging_key, photo.source_bytes)
    encoded, width, height = storage.verify_image(content, photo.content_type)
    extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[
        photo.content_type
    ]
    final_key = (
        f"{storage.PREFIX}final/{listing.owner_id}/{listing.id}/{uuid4()}.{extension}"
    )
    storage.put_final(final_key, encoded, photo.content_type)
    photo.final_key = final_key
    photo.bytes, photo.width, photo.height = len(encoded), width, height
    photo.order = len(_verified_photos(listing))
    photo.state = "verified"
    _bump(listing)
    db.flush()
    # Final object created before commit. A failed DB commit leaves an orphan,
    # never a referenced missing object; scoped cleanup handles it after 24h.


# Complete operations below own the entire transaction. Internal helpers above
# never commit; callers cannot assemble a partial listing/photo workflow.
def policies(db: Session, actor: AccessContext) -> PoliciesResponse:
    with db.begin():
        current_user(db, actor, "host")
        result = PoliciesResponse(
            items=[
                PolicyOutput.model_validate(policy)
                for policy in db.scalars(
                    select(CancellationPolicy).order_by(CancellationPolicy.name)
                )
            ]
        )
    return result


def create_listing(
    db: Session,
    actor: AccessContext,
    guard: Callable[[], None] | None = None,
    *,
    listing_id: UUID | None = None,
) -> ListingResponse:
    with db.begin():
        user = current_user(db, actor, "host")
        if guard is not None:
            guard()
        listing = Listing(
            owner_id=user.id, **({"id": listing_id} if listing_id is not None else {})
        )
        db.add(listing)
        db.flush()
        result = ListingResponse(listing=_listing_output(listing))
    return result


def list_listings(
    db: Session, actor: AccessContext, limit: int = 20, cursor: UUID | None = None
) -> ListingsResponse:
    with db.begin():
        user = current_user(db, actor, "host")
        query = (
            select(Listing)
            .where(Listing.owner_id == user.id)
            .order_by(Listing.id)
            .limit(limit + 1)
        )
        if cursor is not None:
            query = query.where(Listing.id > cursor)
        rows = list(db.scalars(query))
        result = ListingsResponse(
            items=[_listing_output(row) for row in rows[:limit]],
            next_cursor=str(rows[limit - 1].id) if len(rows) > limit else None,
        )
    return result


def get_listing(db: Session, actor: AccessContext, listing_id: UUID) -> ListingResponse:
    with db.begin():
        listing = _owned_listing(db, current_user(db, actor, "host"), listing_id)
        result = ListingResponse(listing=_listing_output(listing))
    return result


def update_listing(
    db: Session,
    actor: AccessContext,
    listing_id: UUID,
    body: ListingPatch,
    guard: Callable[[], None] | None = None,
) -> ListingResponse:
    with db.begin():
        listing = _owned_listing(
            db, current_user(db, actor, "host"), listing_id, lock=True
        )
        if guard is not None:
            guard()
        _check_version(listing, body.version)
        changes = body.model_dump(exclude_unset=True, exclude={"version"})
        if "policy_id" in changes:
            _validate_policy(db, changes["policy_id"])
        for field, value in changes.items():
            setattr(listing, field, value)
        if listing.status == "published":
            _require_publishable(listing)
        _bump(listing)
        db.flush()
        result = ListingResponse(listing=_listing_output(listing))
    return result


def publish(
    db: Session,
    actor: AccessContext,
    listing_id: UUID,
    version: int,
    guard: Callable[[], None] | None = None,
) -> ListingResponse:
    with db.begin():
        listing = _owned_listing(
            db, current_user(db, actor, "host"), listing_id, lock=True
        )
        if guard is not None:
            guard()
        _check_version(listing, version)
        _require_publishable(listing)
        listing.status = "published"
        _bump(listing)
        db.flush()
        result = ListingResponse(listing=_listing_output(listing))
    return result


def unlist(
    db: Session,
    actor: AccessContext,
    listing_id: UUID,
    version: int,
    guard: Callable[[], None] | None = None,
) -> ListingResponse:
    with db.begin():
        listing = _owned_listing(
            db, current_user(db, actor, "host"), listing_id, lock=True
        )
        if guard is not None:
            guard()
        _check_version(listing, version)
        listing.status = "unlisted"
        _bump(listing)
        db.flush()
        result = ListingResponse(listing=_listing_output(listing))
    return result


def create_upload_intent(
    db: Session,
    actor: AccessContext,
    listing_id: UUID,
    body: UploadIntentInput,
    guard: Callable[[], None] | None = None,
) -> UploadIntentResponse:
    with db.begin():
        listing = _owned_listing(
            db, current_user(db, actor, "host"), listing_id, lock=True
        )
        if guard is not None:
            guard()
        photo, url = _create_upload(db, listing, body.content_type, body.bytes)
        result = UploadIntentResponse(
            photo_id=photo.id,
            upload=UploadAuthorization(
                url=url, headers={"Content-Type": photo.content_type}
            ),
        )
    return result


def complete_photo(
    db: Session,
    actor: AccessContext,
    listing_id: UUID,
    photo_id: UUID,
    guard: Callable[[], None] | None = None,
) -> CompleteResponse:
    with db.begin():
        listing = _owned_listing(
            db, current_user(db, actor, "host"), listing_id, lock=True
        )
        if guard is not None:
            guard()
        photo = _own_photo(listing, photo_id)
        _complete_upload(db, listing, photo)
        result = CompleteResponse(
            photo=PhotoOutput.model_validate(photo), listing=_listing_output(listing)
        )
    return result


def delete_photo(
    db: Session,
    actor: AccessContext,
    listing_id: UUID,
    photo_id: UUID,
    guard: Callable[[], None] | None = None,
) -> ListingResponse:
    with db.begin():
        listing = _owned_listing(
            db, current_user(db, actor, "host"), listing_id, lock=True
        )
        if guard is not None:
            guard()
        photo = _own_photo(listing, photo_id)
        if (
            listing.status == "published"
            and photo.state == "verified"
            and len(_verified_photos(listing)) <= 5
        ):
            raise ApiError(
                409,
                "photos_required",
                "Published listings require five verified photos. Unlist before removing this photo.",
            )
        photo.state = "deleted"
        for index, item in enumerate(_verified_photos(listing)):
            item.order = index
        _bump(listing)
        db.flush()
        keys = (photo.staging_key, photo.final_key)
        result = ListingResponse(listing=_listing_output(listing))
    # Database removal committed before any external delete. Failure remains a
    # cleanup backlog, never an attached photo with a missing referenced object.
    for key in keys:
        if key:
            storage.delete_object_best_effort(key)
    return result


def order_photos(
    db: Session,
    actor: AccessContext,
    listing_id: UUID,
    body: PhotoOrderInput,
    guard: Callable[[], None] | None = None,
) -> ListingResponse:
    with db.begin():
        listing = _owned_listing(
            db, current_user(db, actor, "host"), listing_id, lock=True
        )
        if guard is not None:
            guard()
        _check_version(listing, body.version)
        photos = _verified_photos(listing)
        if len(set(body.photo_ids)) != len(body.photo_ids) or set(body.photo_ids) != {
            photo.id for photo in photos
        }:
            raise ApiError(
                422,
                "validation_error",
                "Include every verified photo exactly once.",
                field_errors={
                    "photo_ids": "Include every verified photo exactly once."
                },
            )
        for photo in photos:
            photo.order = body.photo_ids.index(photo.id)
        _bump(listing)
        db.flush()
        result = ListingResponse(listing=_listing_output(listing))
    return result


def read_photo(
    db: Session, actor: AccessContext, listing_id: UUID, photo_id: UUID
) -> PhotoReadResponse:
    with db.begin():
        listing = _owned_listing(db, current_user(db, actor, "host"), listing_id)
        photo = _own_photo(listing, photo_id)
        if photo.state != "verified" or not photo.final_key:
            raise ApiError(404, "not_found", "This verified photo could not be found.")
        result = PhotoReadResponse(url=storage.read_url(photo.final_key))
    return result
