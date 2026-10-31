"""Reservation-scoped private communication; all IDs are server generated."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, now


class Conversation(Base):
    __tablename__ = "conversations"
    reservation_id: Mapped[UUID] = mapped_column(
        ForeignKey("reservations.id"), primary_key=True
    )
    last_sequence: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("reservation_id", "sequence"),
        UniqueConstraint("reservation_id", "sender_id", "idempotency_key"),
        CheckConstraint("sequence > 0", name="message_sequence_positive"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    reservation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.reservation_id"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer)
    sender_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(String(4000))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class MessageRead(Base):
    __tablename__ = "message_reads"
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("messages.id"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class MessageAttachment(Base):
    __tablename__ = "message_attachments"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    reservation_id: Mapped[UUID] = mapped_column(
        ForeignKey("reservations.id"), index=True
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("messages.id"), index=True
    )
    source_key: Mapped[str] = mapped_column(String(512))
    final_key: Mapped[str | None] = mapped_column(String(512))
    content_type: Mapped[str] = mapped_column(String(20))
    bytes: Mapped[int] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
