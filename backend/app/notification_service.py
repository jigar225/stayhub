"""Transaction-scoped writes and recipient-only, cutoff-based acknowledgements."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth_service import AccessContext, current_user
from app.errors import ApiError
from app.models import now
from app.notification_models import Notification


def notify(
    db: Session,
    recipient_id: UUID,
    kind: str,
    source_key: str,
    *,
    title: str,
    href: str,
    actor_id: UUID | None = None,
) -> None:
    if recipient_id == actor_id:
        return
    # Serialize this small write stream until commit, before allocating identity.
    # Thus a later-committed notification cannot acquire an earlier cutoff ID.
    # All callers already own their source transaction/locks; this adds no commit.
    db.execute(text("SELECT pg_advisory_xact_lock(93712641)"))
    db.execute(
        insert(Notification)
        .values(
            recipient_id=recipient_id,
            kind=kind,
            source_key=source_key,
            title=title,
            href=href,
            created_at=now(),
        )
        .on_conflict_do_nothing(constraint="notification_source_recipient")
    )


def page(
    db: Session, actor: AccessContext, before: int | None = None, limit: int = 30
) -> dict[str, Any]:
    with db.begin():
        current_user(db, actor)
        criteria = [Notification.recipient_id == actor.user_id]
        cutoff = db.scalar(select(func.max(Notification.id)).where(*criteria)) or 0
        unread = (
            db.scalar(
                select(func.count())
                .select_from(Notification)
                .where(*criteria, Notification.read_at.is_(None))
            )
            or 0
        )
        if before is not None:
            criteria.append(Notification.id < before)
        rows = list(
            db.scalars(
                select(Notification)
                .where(*criteria)
                .order_by(Notification.id.desc())
                .limit(limit + 1)
            )
        )
        return {
            "items": [
                {
                    "id": row.id,
                    "kind": row.kind,
                    "title": row.title,
                    "href": row.href,
                    "created_at": row.created_at,
                    "read_at": row.read_at,
                }
                for row in rows[:limit]
            ],
            "next_cursor": rows[limit - 1].id if len(rows) > limit else None,
            "unread_count": unread,
            "cutoff": cutoff,
        }


def acknowledge(
    db: Session,
    actor: AccessContext,
    *,
    cutoff: int | None = None,
    notification_id: int | None = None,
    guard: Callable[[], None] | None = None,
) -> dict[str, bool]:
    with db.begin():
        current_user(db, actor)
        if guard:
            guard()
        criteria = [Notification.recipient_id == actor.user_id]
        if notification_id is not None:
            row = db.scalar(
                select(Notification).where(
                    *criteria, Notification.id == notification_id
                )
            )
            if row is None:
                raise ApiError(
                    404, "not_found", "This notification could not be found."
                )
            criteria.append(Notification.id == notification_id)
        else:
            assert cutoff is not None
            criteria.append(Notification.id <= cutoff)
        db.execute(
            update(Notification)
            .where(*criteria, Notification.read_at.is_(None))
            .values(read_at=now())
        )
    return {"ok": True}
