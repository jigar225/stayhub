"""Immutable party reviews and durable review-window sweep checkpoints."""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("reservation_id", "author_id", name="review_one_author"),
        UniqueConstraint("reservation_id", "author_role", name="review_one_role"),
        CheckConstraint("author_role IN ('guest','host')", name="review_role"),
        CheckConstraint(
            "(author_role = 'guest' AND overall BETWEEN 1 AND 5) OR (author_role = 'host' AND overall IS NULL)",
            name="review_rating",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    reservation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reservations.id"), index=True
    )
    listing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("listings.id"), index=True)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    author_role: Mapped[str] = mapped_column(String(5))
    text: Mapped[str] = mapped_column(String(3000))
    overall: Mapped[int | None] = mapped_column(Integer)
    categories: Mapped[dict[str, int]] = mapped_column(JSON)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )


class ReviewWindow(Base):
    __tablename__ = "review_windows"
    reservation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reservations.id"), primary_key=True
    )
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    eligibility_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
