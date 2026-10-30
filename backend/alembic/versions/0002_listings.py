"""Saved owner listings and verified photo lifecycle.

Revision ID: 0002_listings
Revises: 0001_auth
"""

import sqlalchemy as sa

from alembic import op

revision = "0002_listings"
down_revision = "0001_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cancellation_policies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.UniqueConstraint("name", "version"),
    )
    op.create_table(
        "listings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("property_type", sa.String(20)),
        sa.Column("address", sa.String(300)),
        sa.Column("destination", sa.String(100)),
        sa.Column("timezone", sa.String(100)),
        sa.Column("capacity", sa.Integer()),
        sa.Column("bedrooms", sa.Integer()),
        sa.Column("beds", sa.Integer()),
        sa.Column("baths", sa.Integer()),
        sa.Column("title", sa.String(100)),
        sa.Column("description", sa.String(5000)),
        sa.Column("amenities", sa.JSON()),
        sa.Column("house_rules", sa.JSON()),
        sa.Column("nightly_minor", sa.Integer()),
        sa.Column("cleaning_minor", sa.Integer()),
        sa.Column("policy_id", sa.Uuid(), sa.ForeignKey("cancellation_policies.id")),
        sa.Column("booking_mode", sa.String(10)),
        sa.Column("check_in_time", sa.String(5)),
        sa.Column("check_out_time", sa.String(5)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft','published','unlisted')", name="listing_status"
        ),
        sa.CheckConstraint("version >= 1", name="listing_version"),
        sa.CheckConstraint(
            "nightly_minor IS NULL OR nightly_minor BETWEEN 100 AND 10000000",
            name="nightly_bounds",
        ),
        sa.CheckConstraint(
            "cleaning_minor IS NULL OR cleaning_minor BETWEEN 0 AND 1000000",
            name="cleaning_bounds",
        ),
        sa.CheckConstraint(
            "capacity IS NULL OR capacity BETWEEN 1 AND 30", name="capacity_bounds"
        ),
        sa.CheckConstraint(
            "bedrooms IS NULL OR bedrooms BETWEEN 0 AND 20", name="bedrooms_bounds"
        ),
        sa.CheckConstraint("beds IS NULL OR beds BETWEEN 1 AND 30", name="beds_bounds"),
        sa.CheckConstraint(
            "baths IS NULL OR baths BETWEEN 1 AND 20", name="baths_bounds"
        ),
    )
    op.create_index("ix_listings_owner_id", "listings", ["owner_id"])
    op.create_table(
        "listing_photos",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "listing_id", sa.Uuid(), sa.ForeignKey("listings.id"), nullable=False
        ),
        sa.Column("state", sa.String(10), nullable=False),
        sa.Column("staging_key", sa.String(400), nullable=False, unique=True),
        sa.Column("final_key", sa.String(400), unique=True),
        sa.Column("content_type", sa.String(20), nullable=False),
        sa.Column("source_bytes", sa.Integer(), nullable=False),
        sa.Column("bytes", sa.Integer()),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("order", sa.Integer()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('pending','verified','deleted','expired')", name="photo_state"
        ),
        sa.CheckConstraint(
            "source_bytes BETWEEN 1 AND 10485760", name="photo_source_bounds"
        ),
    )
    op.create_index("ix_listing_photos_listing_id", "listing_photos", ["listing_id"])


def downgrade() -> None:
    op.drop_table("listing_photos")
    op.drop_table("listings")
    op.drop_table("cancellation_policies")
