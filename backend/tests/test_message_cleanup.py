"""Real private objects: message cleanup expiry, references, grace and retries."""

from datetime import timedelta
from io import BytesIO
from typing import Any, Literal
from uuid import UUID, uuid4

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_booking import NOW
from test_messages import setup

from app import business_time, message_service, storage, storage_cleanup
from app.config import get_settings
from app.db import get_engine
from app.message_models import MessageAttachment
from app.message_schemas import AttachmentInput, SendInput
from app.models import Reservation, now


@pytest.fixture(autouse=True)
def clock(monkeypatch: Any) -> None:
    monkeypatch.setattr(business_time, "now", lambda: NOW)


def uploaded(
    db: Session, actor: Any, rid: UUID, verified: bool = True
) -> tuple[UUID, str, str | None]:
    data = BytesIO()
    Image.new("RGB", (80, 60), "green").save(data, format="PNG")
    content = data.getvalue()
    intent = message_service.attachment_intent(
        db, actor, rid, AttachmentInput(content_type="image/png", bytes=len(content))
    )
    with db.begin():
        row = db.get(MessageAttachment, intent.attachment_id)
        assert row
        source = row.source_key
    storage.s3_client().put_object(
        Bucket=get_settings().s3_bucket,
        Key=source,
        Body=content,
        ContentType="image/png",
    )
    if verified:
        message_service.complete_attachment(db, actor, rid, intent.attachment_id)
    with db.begin():
        row = db.get(MessageAttachment, intent.attachment_id)
        assert row
        return row.id, source, row.final_key


def keys() -> set[str]:
    return {
        item["Key"]
        for page in storage.s3_client()
        .get_paginator("list_objects_v2")
        .paginate(Bucket=get_settings().s3_bucket, Prefix="stayhub/messages/")
        for item in page.get("Contents", [])
    }


def test_message_cleanup_dry_run_expiry_and_sent_photo_retention(
    monkeypatch: Any,
) -> None:
    base = now()
    with Session(get_engine()) as db:
        _, guest, rid = setup(db)
        sent = uploaded(db, guest, rid)
        message_service.send(
            db, guest, rid, SendInput(attachment_ids=[sent[0]]), "retained-sent-photo"
        )
        unsent = uploaded(db, guest, rid)
        pending = uploaded(db, guest, rid, verified=False)
        active = uploaded(db, guest, rid)
        with db.begin():
            row = db.get(MessageAttachment, active[0])
            assert row
            row.expires_at = base + timedelta(days=4)
    monkeypatch.setattr(storage_cleanup, "now", lambda: base + timedelta(days=2))
    before_keys = keys()
    dry = storage_cleanup.cleanup()
    assert dry["expired_slots"] == 2
    assert keys() == before_keys
    with Session(get_engine()) as db:
        assert db.get(MessageAttachment, unsent[0]) is not None
    applied = storage_cleanup.cleanup(apply=True)
    assert applied["expired_slots"] == 2 and applied["delete_backlog"] == 0
    assert keys() == {sent[2], active[1], active[2]}
    with Session(get_engine()) as db:
        assert db.get(MessageAttachment, sent[0]) is not None
        assert db.get(MessageAttachment, unsent[0]) is None
        assert db.get(MessageAttachment, pending[0]) is None
        assert db.get(MessageAttachment, active[0]) is not None
    assert storage_cleanup.cleanup(apply=True)["delete_backlog"] == 0
    assert keys() == {sent[2], active[1], active[2]}


def test_message_cleanup_orphan_grace_and_fresh_reference_check(
    monkeypatch: Any,
) -> None:
    base = now()
    with Session(get_engine()) as db:
        _, guest, rid = setup(db)
        attachment = uploaded(db, guest, rid)
        with db.begin():
            row = db.get(MessageAttachment, attachment[0])
            assert row
            row.expires_at = base + timedelta(days=4)
    orphan = f"stayhub/messages/verified/{attachment[0]}/{uuid4()}"
    storage.s3_client().put_object(
        Bucket=get_settings().s3_bucket, Key=orphan, Body=b"rollback pixel-only object"
    )
    monkeypatch.setattr(storage_cleanup, "now", lambda: base + timedelta(hours=1))
    storage_cleanup.cleanup(apply=True)
    assert orphan in keys()  # Failed-commit object gets a full 24h grace.
    monkeypatch.setattr(storage_cleanup, "now", lambda: base + timedelta(days=2))
    real_client = storage.s3_client

    class Client:
        def get_paginator(self, operation: Literal["list_objects_v2"]) -> Any:
            actual = real_client().get_paginator(operation)

            class Paginator:
                def paginate(self, **kwargs: Any) -> Any:
                    pages = actual.paginate(**kwargs)
                    if kwargs["Prefix"] == "stayhub/messages/verified/":
                        # Commit a new reference after the expired-slot pass,
                        # before the orphan scan, like a concurrent completion.
                        with Session(get_engine()) as db, db.begin():
                            db.execute(
                                select(MessageAttachment.reservation_id).where(
                                    MessageAttachment.id == attachment[0]
                                )
                            )

                            db.execute(
                                select(Reservation.id)
                                .where(Reservation.id == rid)
                                .with_for_update()
                            )
                            row = db.scalar(
                                select(MessageAttachment)
                                .where(MessageAttachment.id == attachment[0])
                                .with_for_update()
                            )
                            assert row
                            row.final_key = orphan
                    return pages

            return Paginator()

    monkeypatch.setattr(storage_cleanup, "s3_client", lambda: Client())
    applied = storage_cleanup.cleanup(apply=True)
    assert applied["orphan_objects"] == 1
    assert orphan in keys() and attachment[2] not in keys()


def test_message_cleanup_failed_delete_remains_retryable(monkeypatch: Any) -> None:
    base = now()
    with Session(get_engine()) as db:
        _, guest, rid = setup(db)
        attachment = uploaded(db, guest, rid)
    monkeypatch.setattr(storage_cleanup, "now", lambda: base + timedelta(hours=1))
    real_delete = storage.delete_object_best_effort
    monkeypatch.setattr(
        storage_cleanup,
        "delete_object_best_effort",
        lambda key: False if key == attachment[2] else real_delete(key),
    )
    failed = storage_cleanup.cleanup(apply=True)
    assert failed["delete_backlog"] == 1
    with Session(get_engine()) as db:
        row = db.get(MessageAttachment, attachment[0])
        assert row and row.final_key == attachment[2]
    monkeypatch.setattr(storage_cleanup, "delete_object_best_effort", real_delete)
    retried = storage_cleanup.cleanup(apply=True)
    assert retried["delete_backlog"] == 0
    with Session(get_engine()) as db:
        assert db.get(MessageAttachment, attachment[0]) is None
    assert attachment[2] not in keys()
