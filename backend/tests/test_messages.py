"""Private messaging, immutable uploads and exact loaded-message acknowledgements."""

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from typing import Any
from uuid import UUID, uuid4

import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_booking import quote
from test_discovery import published
from test_services import account

from app import booking_service, business_time, message_service, storage
from app.booking_schemas import DeclineInput
from app.config import get_settings
from app.db import get_engine
from app.errors import ApiError
from app.message_models import Conversation, Message, MessageAttachment
from app.message_schemas import AttachmentInput, ReadInput, SendInput


def setup(db: Session) -> tuple[Any, Any, UUID]:
    host, lid = published(db, booking_mode="request")
    guest, _ = account(db)
    body = quote(db, lid)
    saved = booking_service.pay(db, guest, body, str(uuid4()))
    return host, guest, saved.reservation.id


@pytest.fixture(autouse=True)
def clock(monkeypatch: Any) -> None:
    from test_booking import NOW

    monkeypatch.setattr(business_time, "now", lambda: NOW)


def test_parties_lazy_conversation_exact_ack_and_terminal_access() -> None:
    with Session(get_engine()) as db:
        host, guest, rid = setup(db)
        outsider, _ = account(db)
        with db.begin():
            assert db.scalar(select(func.count()).select_from(Conversation)) == 0
        with pytest.raises(ApiError) as denied:
            message_service.history(db, outsider, rid)
        assert denied.value.status == 404
        assert message_service.history(db, guest, rid).items == []
        for n in range(4):
            message_service.send(
                db, host, rid, SendInput(text=f"Host message{n}"), f"message-key-{n}"
            )
        loaded = message_service.history(db, guest, rid, limit=2)
        assert [m.sequence for m in loaded.items] == [3, 4]
        assert loaded.unread_count == 4 and loaded.next_cursor == 3
        message_service.send(
            db, host, rid, SendInput(text="Later arrival"), "message-key-later"
        )
        acknowledged = message_service.acknowledge(
            db, guest, rid, ReadInput(acknowledged_cursor=loaded.acknowledged_cursor)
        )
        assert (
            acknowledged["unread_count"] == 3
        )  # two earlier unloaded plus later arrival
        earlier = message_service.history(
            db, guest, rid, before=loaded.next_cursor, limit=2
        )
        assert [m.sequence for m in earlier.items] == [1, 2]
        assert earlier.next_cursor is None
        assert (
            message_service.acknowledge(
                db,
                guest,
                rid,
                ReadInput(acknowledged_cursor=earlier.acknowledged_cursor),
            )["unread_count"]
            == 1
        )
        with pytest.raises(ApiError):
            message_service.acknowledge(
                db, host, rid, ReadInput(acknowledged_cursor=loaded.acknowledged_cursor)
            )
        inbox = message_service.inbox(db, guest, "guest")
        assert inbox.items[0].last_message_preview == "Later arrival"
        assert inbox.unread_count == 1
        assert message_service.inbox(db, outsider, "guest").items == []
        booking_service.host_decision(
            db,
            host,
            rid,
            "decline",
            DeclineInput(reason="Messaging terminal-state regression"),
            "terminal-decline-key",
        )
        assert (
            message_service.send(
                db, guest, rid, SendInput(text="Thanks anyway"), "terminal-message"
            ).message.text
            == "Thanks anyway"
        )


def test_idempotent_concurrent_send_and_conflicting_payload() -> None:
    with Session(get_engine()) as db:
        host, guest, rid = setup(db)

    def send() -> UUID:
        with Session(get_engine()) as db:
            return message_service.send(
                db, guest, rid, SendInput(text="Same message"), "stable-retry-key"
            ).message.id

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: send(), range(2)))
    assert ids[0] == ids[1]
    with Session(get_engine()) as db:
        with db.begin():
            assert db.scalar(select(func.count()).select_from(Message)) == 1
        with pytest.raises(ApiError) as conflict:
            message_service.send(
                db, guest, rid, SendInput(text="Changed message"), "stable-retry-key"
            )
        assert conflict.value.status == 409
        with pytest.raises(ApiError):
            message_service.send(db, guest, rid, SendInput(text="No key"), "")
        assert message_service.inbox(db, host, "host").unread_count == 1


def test_verified_attachments_private_ownership_reuse_and_metadata() -> None:
    with Session(get_engine()) as db:
        host, guest, rid = setup(db)
        outsider, _ = account(db)
        raw = BytesIO()
        Image.new("RGB", (80, 60), "green").save(raw, format="PNG")
        data = raw.getvalue()
        intent = message_service.attachment_intent(
            db, guest, rid, AttachmentInput(content_type="image/png", bytes=len(data))
        )
        with db.begin():
            attachment = db.get(MessageAttachment, intent.attachment_id)
            assert attachment
            key = attachment.source_key
        storage.s3_client().put_object(
            Bucket=get_settings().s3_bucket,
            Key=key,
            Body=data,
            ContentType="image/png",
        )
        with pytest.raises(ApiError):
            message_service.send(
                db,
                guest,
                rid,
                SendInput(attachment_ids=[intent.attachment_id]),
                "unverified-key",
            )
        with pytest.raises(ApiError) as denied:
            message_service.complete_attachment(db, outsider, rid, intent.attachment_id)
        assert denied.value.status == 404
        photo = message_service.complete_attachment(
            db, guest, rid, intent.attachment_id
        )
        assert (photo.width, photo.height) == (80, 60)
        with pytest.raises(ApiError):
            message_service.send(
                db,
                host,
                rid,
                SendInput(attachment_ids=[intent.attachment_id]),
                "stolen-photo-key",
            )
        sent = message_service.send(
            db,
            guest,
            rid,
            SendInput(
                text="<script>alert(1)</script>", attachment_ids=[intent.attachment_id]
            ),
            "verified-photo-key",
        )
        assert len(sent.message.attachments) == 1
        assert message_service.history(db, host, rid).items[0].attachments[0].url
        with pytest.raises(ApiError):
            message_service.send(
                db,
                guest,
                rid,
                SendInput(attachment_ids=[intent.attachment_id]),
                "reused-photo-key",
            )
        with pytest.raises(ApiError):
            message_service.history(db, outsider, rid)


def test_invalid_photo_content_is_not_verified() -> None:
    with Session(get_engine()) as db:
        _, guest, rid = setup(db)
        data = b"pretend image"
        intent = message_service.attachment_intent(
            db, guest, rid, AttachmentInput(content_type="image/png", bytes=len(data))
        )
        with db.begin():
            attachment = db.get(MessageAttachment, intent.attachment_id)
            assert attachment
            key = attachment.source_key
        storage.s3_client().put_object(
            Bucket=get_settings().s3_bucket,
            Key=key,
            Body=data,
            ContentType="image/png",
        )
        with pytest.raises(ApiError) as invalid:
            message_service.complete_attachment(db, guest, rid, intent.attachment_id)
        assert invalid.value.code == "upload_invalid"
        with db.begin():
            attachment = db.get(MessageAttachment, intent.attachment_id)
            assert attachment and attachment.final_key is None
