from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    column,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, ExcludeConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(512))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now
    )
    memberships: Mapped[list[UserRole]] = relationship(lazy="selectin")


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (
        CheckConstraint("role IN ('guest', 'host', 'admin')", name="valid_role"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(10), primary_key=True)


class AuthSession(Base):
    __tablename__ = "sessions"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    csrf_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now
    )


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CancellationPolicy(Base):
    __tablename__ = "cancellation_policies"
    __table_args__ = (UniqueConstraint("name", "version"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(20))
    version: Mapped[int] = mapped_column(Integer)
    definition: Mapped[dict[str, object]] = mapped_column(JSON)


class Listing(Base):
    __tablename__ = "listings"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','published','unlisted')", name="listing_status"
        ),
        CheckConstraint("version >= 1", name="listing_version"),
        CheckConstraint(
            "nightly_minor IS NULL OR nightly_minor BETWEEN 100 AND 10000000",
            name="nightly_bounds",
        ),
        CheckConstraint(
            "cleaning_minor IS NULL OR cleaning_minor BETWEEN 0 AND 1000000",
            name="cleaning_bounds",
        ),
        CheckConstraint(
            "capacity IS NULL OR capacity BETWEEN 1 AND 30", name="capacity_bounds"
        ),
        CheckConstraint(
            "bedrooms IS NULL OR bedrooms BETWEEN 0 AND 20", name="bedrooms_bounds"
        ),
        CheckConstraint("beds IS NULL OR beds BETWEEN 1 AND 30", name="beds_bounds"),
        CheckConstraint("baths IS NULL OR baths BETWEEN 1 AND 20", name="baths_bounds"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(12), default="draft")
    version: Mapped[int] = mapped_column(Integer, default=1)
    property_type: Mapped[str | None] = mapped_column(String(20))
    address: Mapped[str | None] = mapped_column(String(300))
    destination: Mapped[str | None] = mapped_column(String(100))
    timezone: Mapped[str | None] = mapped_column(String(100))
    capacity: Mapped[int | None] = mapped_column(Integer)
    bedrooms: Mapped[int | None] = mapped_column(Integer)
    beds: Mapped[int | None] = mapped_column(Integer)
    baths: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(5000))
    categories: Mapped[list[str]] = mapped_column(
        ARRAY(String(20)), default=list, server_default=text("'{}'"), nullable=False
    )
    amenities: Mapped[list[str] | None] = mapped_column(JSON)
    house_rules: Mapped[list[str] | None] = mapped_column(JSON)
    nightly_minor: Mapped[int | None] = mapped_column(Integer)
    cleaning_minor: Mapped[int | None] = mapped_column(Integer)
    policy_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cancellation_policies.id")
    )
    booking_mode: Mapped[str | None] = mapped_column(String(10))
    check_in_time: Mapped[str | None] = mapped_column(String(5), default="15:00")
    check_out_time: Mapped[str | None] = mapped_column(String(5), default="11:00")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now, onupdate=now
    )
    photos: Mapped[list[ListingPhoto]] = relationship(lazy="selectin")


class ListingPhoto(Base):
    __tablename__ = "listing_photos"
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending','verified','deleted','expired')", name="photo_state"
        ),
        CheckConstraint(
            "source_bytes BETWEEN 1 AND 10485760", name="photo_source_bounds"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    listing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("listings.id"), index=True)
    state: Mapped[str] = mapped_column(String(10), default="pending")
    staging_key: Mapped[str] = mapped_column(String(400), unique=True)
    final_key: Mapped[str | None] = mapped_column(String(400), unique=True)
    content_type: Mapped[str] = mapped_column(String(20))
    source_bytes: Mapped[int] = mapped_column(Integer)
    bytes: Mapped[int | None] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    order: Mapped[int | None] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CalendarEntry(Base):
    __tablename__ = "calendar_entries"
    __table_args__ = (
        CheckConstraint("check_in < check_out", name="occupancy_date_order"),
        CheckConstraint(
            "(kind = 'block' AND reservation_id IS NULL) OR (kind = 'reservation' AND reservation_id IS NOT NULL)",
            name="occupancy_reference",
        ),
        ExcludeConstraint(
            ("listing_id", "="),
            (func.daterange(column("check_in"), column("check_out"), "[)"), "&&"),
            where=text("active"),
            using="gist",
            name="no_active_occupancy_overlap",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    listing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("listings.id"), index=True)
    kind: Mapped[str] = mapped_column(String(12), default="block")
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reservations.id"), unique=True
    )
    check_in: Mapped[date] = mapped_column(Date)
    check_out: Mapped[date] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DemoImport(Base):
    __tablename__ = "demo_imports"
    demo_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    listing_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("listings.id"), unique=True
    )
    expected_version: Mapped[int] = mapped_column(Integer)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)


class DemoAssetPhoto(Base):
    __tablename__ = "demo_asset_photos"
    demo_key: Mapped[str] = mapped_column(
        ForeignKey("demo_imports.demo_key"), primary_key=True
    )
    asset_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    photo_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("listing_photos.id"), unique=True
    )


class Reservation(Base):
    __tablename__ = "reservations"
    __table_args__ = (
        UniqueConstraint("id", "total_minor", name="reservation_charge_reference"),
        CheckConstraint(
            "state IN ('pending','confirmed','checked_in','completed','declined','cancelled_by_guest','cancelled_by_host')",
            name="reservation_state",
        ),
        CheckConstraint(
            "booking_mode IN ('instant','request')", name="reservation_mode"
        ),
        CheckConstraint(
            "check_in < check_out AND check_out - check_in BETWEEN 1 AND 180",
            name="reservation_dates",
        ),
        CheckConstraint("guests BETWEEN 1 AND 30", name="reservation_guests"),
        CheckConstraint(
            "scheduled_check_out > scheduled_check_in", name="reservation_schedule"
        ),
        CheckConstraint(
            "(booking_mode = 'instant' AND request_deadline IS NULL) OR (booking_mode = 'request' AND request_deadline = created_at + interval '24 hours')",
            name="reservation_deadline",
        ),
        CheckConstraint(
            "nightly_minor >= 0 AND nights_minor >= 0 AND cleaning_minor >= 0 AND subtotal_minor = nights_minor + cleaning_minor AND guest_fee_minor = (subtotal_minor * 14::bigint + 50) / 100 AND total_minor = subtotal_minor + guest_fee_minor AND host_fee_minor = (subtotal_minor * 3::bigint + 50) / 100",
            name="reservation_money",
        ),
        CheckConstraint(
            "financial_version >= 1 AND ((state IN ('pending','confirmed','checked_in','completed') AND effective_host_fee_minor = host_fee_minor AND host_entitlement_minor = subtotal_minor - host_fee_minor AND platform_entitlement_minor = guest_fee_minor + host_fee_minor) OR (state IN ('declined','cancelled_by_host') AND effective_host_fee_minor = 0 AND host_entitlement_minor = 0 AND platform_entitlement_minor = 0) OR (state = 'cancelled_by_guest' AND host_entitlement_minor >= 0 AND host_entitlement_minor + effective_host_fee_minor BETWEEN 0 AND nights_minor AND effective_host_fee_minor = ((host_entitlement_minor + effective_host_fee_minor) * 3::bigint + 50) / 100 AND platform_entitlement_minor BETWEEN effective_host_fee_minor AND guest_fee_minor + effective_host_fee_minor))",
            name="reservation_entitlements",
        ),
        CheckConstraint("guest_id <> host_id", name="reservation_distinct_parties"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(24), unique=True)
    listing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("listings.id"), index=True)
    guest_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    host_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    state: Mapped[str] = mapped_column(String(24), index=True)
    reason: Mapped[str | None] = mapped_column(String(500))
    booking_mode: Mapped[str] = mapped_column(String(10))
    check_in: Mapped[date] = mapped_column(Date)
    check_out: Mapped[date] = mapped_column(Date)
    guests: Mapped[int] = mapped_column(Integer)
    timezone: Mapped[str] = mapped_column(String(100))
    scheduled_check_in: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    scheduled_check_out: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    request_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    listing_snapshot: Mapped[dict[str, object]] = mapped_column(JSON)
    policy_snapshot: Mapped[dict[str, object]] = mapped_column(JSON)
    nightly_minor: Mapped[int] = mapped_column(Integer)
    nights_minor: Mapped[int] = mapped_column(Integer)
    cleaning_minor: Mapped[int] = mapped_column(Integer)
    subtotal_minor: Mapped[int] = mapped_column(Integer)
    guest_fee_minor: Mapped[int] = mapped_column(Integer)
    total_minor: Mapped[int] = mapped_column(Integer)
    host_fee_minor: Mapped[int] = mapped_column(Integer)
    host_entitlement_minor: Mapped[int] = mapped_column(Integer)
    platform_entitlement_minor: Mapped[int] = mapped_column(Integer)
    financial_version: Mapped[int] = mapped_column(Integer, default=1)
    effective_host_fee_minor: Mapped[int] = mapped_column(Integer, default=0)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["reservation_id", "amount_minor"],
            ["reservations.id", "reservations.total_minor"],
            name="payment_matches_charge",
        ),
        UniqueConstraint(
            "id", "reservation_id", "amount_minor", name="payment_refund_reference"
        ),
        CheckConstraint("amount_minor >= 0 AND currency = 'EUR'", name="payment_money"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    reservation_id: Mapped[uuid.UUID] = mapped_column(unique=True)
    operation_id: Mapped[str] = mapped_column(String(80), unique=True)
    amount_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Refund(Base):
    __tablename__ = "refunds"
    __table_args__ = (
        ForeignKeyConstraint(
            ["payment_id", "reservation_id", "original_charge_minor"],
            ["payments.id", "payments.reservation_id", "payments.amount_minor"],
            name="refund_matches_original_charge",
        ),
        CheckConstraint(
            "amount_minor >= 0 AND amount_minor <= original_charge_minor AND nights_minor >= 0 AND cleaning_minor >= 0 AND guest_fee_minor >= 0 AND amount_minor = nights_minor + cleaning_minor + guest_fee_minor",
            name="refund_money",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    original_charge_minor: Mapped[int] = mapped_column(Integer)
    payment_id: Mapped[uuid.UUID] = mapped_column(unique=True)
    reservation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reservations.id"), unique=True
    )
    operation_id: Mapped[str] = mapped_column(String(80), unique=True)
    amount_minor: Mapped[int] = mapped_column(Integer)
    nights_minor: Mapped[int] = mapped_column(Integer)
    cleaning_minor: Mapped[int] = mapped_column(Integer)
    guest_fee_minor: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(500))
    refunded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("actor_id", "operation", "key", name="idempotency_scope"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    operation: Mapped[str] = mapped_column(String(100))
    key: Mapped[str] = mapped_column(String(128))
    fingerprint: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int] = mapped_column(Integer)
    response_body: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class EventLog(Base):
    __tablename__ = "event_log"
    __table_args__ = (
        UniqueConstraint("action", "target_id", name="event_business_identity"),
        CheckConstraint(
            "(actor_id IS NOT NULL AND system_identity IS NULL) OR (actor_id IS NULL AND system_identity IS NOT NULL)",
            name="event_actor",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    system_identity: Mapped[str | None] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(60))
    target_type: Mapped[str] = mapped_column(String(30))
    target_id: Mapped[uuid.UUID] = mapped_column(index=True)
    before: Mapped[dict[str, object] | None] = mapped_column(JSON)
    after: Mapped[dict[str, object]] = mapped_column(JSON)
    business_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Payout(Base):
    __tablename__ = "payouts"
    __table_args__ = (
        CheckConstraint(
            "gross_minor >= 0 AND host_fee_minor >= 0 AND net_minor >= 0 AND gross_minor - host_fee_minor = net_minor AND (status <> 'cancelled' OR net_minor = 0)",
            name="payout_money",
        ),
        CheckConstraint(
            "status IN ('held','scheduled','paid','cancelled')", name="payout_status"
        ),
        CheckConstraint(
            "(status = 'paid' AND paid_at IS NOT NULL AND release_operation IS NOT NULL AND net_minor > 0) OR (status <> 'paid' AND paid_at IS NULL AND release_operation IS NULL)",
            name="payout_release",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    reservation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reservations.id"), unique=True
    )
    host_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    gross_minor: Mapped[int] = mapped_column(Integer)
    host_fee_minor: Mapped[int] = mapped_column(Integer)
    net_minor: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12), index=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    release_operation: Mapped[str | None] = mapped_column(String(80), unique=True)


class AppClock(Base):
    __tablename__ = "app_clock"
    __table_args__ = (
        CheckConstraint(
            "id = 1 AND offset_seconds >= 0 AND version >= 1", name="clock_forward"
        ),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    offset_seconds: Mapped[int] = mapped_column(BigInteger, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
