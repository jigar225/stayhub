"""Party-only conversation operations. Source writes and notifications commit together."""

import hashlib
import json
from collections.abc import Callable
from datetime import timedelta
from uuid import UUID, uuid4

import jwt
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import storage
from app.auth_service import AccessContext, current_user
from app.config import get_settings
from app.errors import ApiError
from app.message_models import Conversation, Message, MessageAttachment, MessageRead
from app.message_schemas import (
    AttachmentInput,
    AttachmentIntent,
    AttachmentOutput,
    InboxItem,
    InboxPage,
    MessageOutput,
    MessagePage,
    ReadInput,
    SendInput,
    SendOutput,
)
from app.models import Reservation, User, now

Guard = Callable[[], None] | None


def _party(
    db: Session, actor: AccessContext, rid: UUID, lock: bool = False
) -> tuple[Reservation, User]:
    user = current_user(db, actor)
    row = (
        db.scalar(select(Reservation).where(Reservation.id == rid).with_for_update())
        if lock
        else db.get(Reservation, rid)
    )
    roles = {r.role for r in user.memberships}
    if row is None or not (
        (row.guest_id == user.id and "guest" in roles)
        or (row.host_id == user.id and "host" in roles)
    ):
        raise ApiError(404, "not_found", "This conversation could not be found.")
    return row, user


def _conversation(db: Session, rid: UUID) -> Conversation:
    row = db.get(Conversation, rid)
    if row is None:
        row = Conversation(reservation_id=rid)
        db.add(row)
        db.flush()
    return row


def _unread(db: Session, rid: UUID, uid: UUID) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(Message)
            .where(
                Message.reservation_id == rid,
                Message.sender_id != uid,
                ~select(MessageRead.message_id)
                .where(MessageRead.message_id == Message.id, MessageRead.user_id == uid)
                .exists(),
            )
        )
        or 0
    )


def _outputs(db: Session, rows: list[Message]) -> list[MessageOutput]:
    attachments: dict[UUID, list[AttachmentOutput]] = {}
    if rows:
        for item in db.scalars(
            select(MessageAttachment).where(
                MessageAttachment.message_id.in_([m.id for m in rows])
            )
        ):
            if item.final_key and item.message_id is not None:
                attachments.setdefault(item.message_id, []).append(
                    AttachmentOutput(
                        id=item.id,
                        url=storage.read_url(item.final_key),
                        expires_at=now() + timedelta(minutes=5),
                        width=item.width or 0,
                        height=item.height or 0,
                    )
                )
    return [
        MessageOutput(
            id=m.id,
            sequence=m.sequence,
            sender_id=m.sender_id,
            text=m.text,
            created_at=m.created_at,
            attachments=attachments.get(m.id, []),
        )
        for m in rows
    ]


def history(
    db: Session,
    actor: AccessContext,
    rid: UUID,
    before: int | None = None,
    limit: int = 30,
) -> MessagePage:
    with db.begin():
        reservation, user = _party(db, actor, rid, lock=True)
        _conversation(db, rid)
        query = select(Message).where(Message.reservation_id == rid)
        if before is not None:
            query = query.where(Message.sequence < before)
        rows = list(
            db.scalars(query.order_by(Message.sequence.desc()).limit(limit + 1))
        )
        page = list(reversed(rows[:limit]))
        token = jwt.encode(
            {
                "purpose": "message-read",
                "uid": str(user.id),
                "rid": str(rid),
                "ids": [str(m.id) for m in page],
                "exp": now() + timedelta(hours=1),
            },
            get_settings().jwt_secret.get_secret_value(),
            algorithm="HS256",
        )
        result = MessagePage(
            items=_outputs(db, page),
            next_cursor=page[0].sequence if len(rows) > limit else None,
            acknowledged_cursor=token,
            unread_count=_unread(db, rid, user.id),
            reservation_code=reservation.code,
            listing_title=str(reservation.listing_snapshot["title"]),
        )
    return result


def acknowledge(
    db: Session, actor: AccessContext, rid: UUID, body: ReadInput, guard: Guard = None
) -> dict[str, int]:
    with db.begin():
        _, user = _party(db, actor, rid)
        if guard:
            guard()
        try:
            payload = jwt.decode(
                body.acknowledged_cursor,
                get_settings().jwt_secret.get_secret_value(),
                algorithms=["HS256"],
            )
            if (
                payload.get("purpose") != "message-read"
                or payload.get("uid") != str(user.id)
                or payload.get("rid") != str(rid)
            ):
                raise ValueError("cursor binding")
            ids = [UUID(v) for v in payload["ids"]]
        except (jwt.PyJWTError, ValueError, TypeError, KeyError):
            raise ApiError(
                422, "invalid_cursor", "Reload messages before marking them read."
            ) from None
        if ids:
            eligible = list(
                db.scalars(
                    select(Message.id).where(
                        Message.id.in_(ids),
                        Message.reservation_id == rid,
                        Message.sender_id != user.id,
                    )
                )
            )
            if eligible:
                db.execute(
                    insert(MessageRead)
                    .values([{"message_id": m, "user_id": user.id} for m in eligible])
                    .on_conflict_do_nothing()
                )
        result = {"unread_count": _unread(db, rid, user.id)}
    return result


def send(
    db: Session,
    actor: AccessContext,
    rid: UUID,
    body: SendInput,
    key: str,
    guard: Guard = None,
) -> SendOutput:
    if not 8 <= len(key) <= 128 or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise ApiError(
            422,
            "idempotency_required",
            "Use an idempotency key of8–128 visible characters.",
        )
    request_hash = hashlib.sha256(
        json.dumps(body.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()
    with db.begin():
        reservation, user = _party(db, actor, rid, lock=True)
        if guard:
            guard()
        previous = db.scalar(
            select(Message).where(
                Message.reservation_id == rid,
                Message.sender_id == user.id,
                Message.idempotency_key == key,
            )
        )
        if previous is not None:
            if previous.request_hash != request_hash:
                raise ApiError(
                    409,
                    "idempotency_conflict",
                    "This send key belongs to a different message.",
                )
            return SendOutput(message=_outputs(db, [previous])[0])
        conversation = _conversation(db, rid)
        attachments = (
            list(
                db.scalars(
                    select(MessageAttachment)
                    .where(MessageAttachment.id.in_(body.attachment_ids))
                    .with_for_update()
                )
            )
            if body.attachment_ids
            else []
        )
        if len(attachments) != len(body.attachment_ids) or any(
            a.owner_id != user.id
            or a.reservation_id != rid
            or a.message_id is not None
            or not a.final_key
            or a.expires_at <= now()
            for a in attachments
        ):
            raise ApiError(
                422,
                "attachment_invalid",
                "Use your verified, unexpired photos for this conversation only.",
            )
        conversation.last_sequence += 1
        conversation.updated_at = now()
        message = Message(
            reservation_id=rid,
            sequence=conversation.last_sequence,
            sender_id=user.id,
            text=body.text,
            idempotency_key=key,
            request_hash=request_hash,
        )
        db.add(message)
        db.flush()
        for attachment in attachments:
            attachment.message_id = message.id
        db.flush()
        from app.notification_service import notify

        recipient = (
            reservation.host_id
            if user.id == reservation.guest_id
            else reservation.guest_id
        )
        notify(
            db,
            recipient,
            "new_message",
            str(message.id),
            title="New reservation message",
            href=f"/messages/{rid}",
            actor_id=user.id,
        )
        result = SendOutput(message=_outputs(db, [message])[0])
    return result


def inbox(
    db: Session,
    actor: AccessContext,
    role: str,
    cursor: UUID | None = None,
    limit: int = 30,
) -> InboxPage:
    with db.begin():
        user = current_user(db, actor, role)
        owned = (
            Reservation.host_id == user.id
            if role == "host"
            else Reservation.guest_id == user.id
        )
        q = (
            select(Reservation, Conversation)
            .join(Conversation, Conversation.reservation_id == Reservation.id)
            .where(owned)
        )
        if cursor:
            q = q.where(Reservation.id > cursor)
        rows = list(db.execute(q.order_by(Reservation.id).limit(limit + 1)))
        ids = [r.id for r, c in rows[:limit]]
        last = (
            {
                m.reservation_id: m
                for m in db.scalars(
                    select(Message)
                    .join(
                        Conversation,
                        Conversation.reservation_id == Message.reservation_id,
                    )
                    .where(
                        Message.reservation_id.in_(ids),
                        Message.sequence == Conversation.last_sequence,
                    )
                )
            }
            if ids
            else {}
        )
        counterpart_ids = [
            r.guest_id if role == "host" else r.host_id for r, c in rows[:limit]
        ]
        names = (
            {
                u.id: u.name
                for u in db.scalars(select(User).where(User.id.in_(counterpart_ids)))
            }
            if counterpart_ids
            else {}
        )
        unread = dict(
            db.execute(
                select(Message.reservation_id, func.count())
                .join(Reservation, Reservation.id == Message.reservation_id)
                .where(
                    owned,
                    Message.sender_id != user.id,
                    ~select(MessageRead.message_id)
                    .where(
                        MessageRead.message_id == Message.id,
                        MessageRead.user_id == user.id,
                    )
                    .exists(),
                )
                .group_by(Message.reservation_id)
            ).all()
        )
        items = []
        for r, c in rows[:limit]:
            message = last.get(r.id)
            items.append(
                InboxItem(
                    reservation_id=r.id,
                    reservation_code=r.code,
                    listing_title=str(r.listing_snapshot["title"]),
                    counterpart_name=names.get(
                        r.guest_id if role == "host" else r.host_id, "StayHub member"
                    ),
                    unread_count=int(unread.get(r.id, 0)),
                    last_message_preview=(message.text[:160] or "Photo attachment")
                    if message
                    else "No messages yet",
                    updated_at=c.updated_at,
                )
            )
        result = InboxPage(
            items=items,
            next_cursor=rows[limit - 1][0].id if len(rows) > limit else None,
            unread_count=sum(int(v) for v in unread.values()),
        )
    return result


def attachment_intent(
    db: Session,
    actor: AccessContext,
    rid: UUID,
    body: AttachmentInput,
    guard: Guard = None,
) -> AttachmentIntent:
    with db.begin():
        _, user = _party(db, actor, rid, lock=True)
        if guard:
            guard()
        active = int(
            db.scalar(
                select(func.count())
                .select_from(MessageAttachment)
                .where(
                    MessageAttachment.owner_id == user.id,
                    MessageAttachment.reservation_id == rid,
                    MessageAttachment.message_id.is_(None),
                    MessageAttachment.expires_at > now(),
                )
            )
            or 0
        )
        if active >= 12:
            raise ApiError(
                429,
                "upload_limit",
                "Finish sending your existing photos before uploading more.",
            )
        aid = uuid4()
        expires = now() + timedelta(minutes=30)
        item = MessageAttachment(
            id=aid,
            reservation_id=rid,
            owner_id=user.id,
            source_key=f"stayhub/messages/staging/{aid}/{uuid4()}",
            content_type=body.content_type,
            bytes=body.bytes,
            expires_at=expires,
        )
        db.add(item)
        db.flush()
        result = AttachmentIntent(
            attachment_id=aid,
            upload_url=storage.upload_url(
                item.source_key, item.content_type, item.bytes
            ),
            expires_at=expires,
        )
    return result


def complete_attachment(
    db: Session, actor: AccessContext, rid: UUID, aid: UUID, guard: Guard = None
) -> AttachmentOutput:
    with db.begin():
        _, user = _party(db, actor, rid, lock=True)
        if guard:
            guard()
        item = db.scalar(
            select(MessageAttachment)
            .where(MessageAttachment.id == aid)
            .with_for_update()
        )
        if item is None or item.owner_id != user.id or item.reservation_id != rid:
            raise ApiError(404, "not_found", "This photo could not be found.")
        if item.expires_at <= now() or item.message_id is not None:
            raise ApiError(
                409, "attachment_expired", "Create a new photo upload before sending."
            )
        if not item.final_key:
            content = storage.read_source(item.source_key, item.bytes)
            encoded, width, height = storage.verify_image(content, item.content_type)
            final = f"stayhub/messages/verified/{aid}/{uuid4()}"
            storage.put_final(final, encoded, item.content_type)
            item.final_key = final
            item.width = width
            item.height = height
        result = AttachmentOutput(
            id=item.id,
            url=storage.read_url(item.final_key),
            expires_at=now() + timedelta(minutes=5),
            width=item.width or 0,
            height=item.height or 0,
        )
    return result
