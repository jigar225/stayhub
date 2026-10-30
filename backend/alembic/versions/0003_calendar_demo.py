"""Shared occupancy exclusion and non-destructive content import markers."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ExcludeConstraint

from alembic import op

revision = "0003_calendar_demo"
down_revision = "0002_listings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_table(
        "calendar_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "listing_id", sa.Uuid(), sa.ForeignKey("listings.id"), nullable=False
        ),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("reservation_id", sa.Uuid()),
        sa.Column("check_in", sa.Date(), nullable=False),
        sa.Column("check_out", sa.Date(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("check_in < check_out", name="occupancy_date_order"),
        sa.CheckConstraint(
            "(kind = 'block' AND reservation_id IS NULL) OR (kind = 'reservation' AND reservation_id IS NOT NULL)",
            name="occupancy_reference",
        ),
        ExcludeConstraint(
            ("listing_id", "="),
            (
                sa.func.daterange(sa.column("check_in"), sa.column("check_out"), "[)"),
                "&&",
            ),
            where=sa.text("active"),
            using="gist",
            name="no_active_occupancy_overlap",
        ),
    )
    op.create_index(
        "ix_calendar_entries_listing_id", "calendar_entries", ["listing_id"]
    )
    op.create_table(
        "demo_imports",
        sa.Column("demo_key", sa.String(100), primary_key=True),
        sa.Column(
            "listing_id",
            sa.Uuid(),
            sa.ForeignKey("listings.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("expected_version", sa.Integer(), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "demo_asset_photos",
        sa.Column(
            "demo_key",
            sa.String(100),
            sa.ForeignKey("demo_imports.demo_key"),
            primary_key=True,
        ),
        sa.Column("asset_id", sa.String(100), primary_key=True),
        sa.Column(
            "photo_id",
            sa.Uuid(),
            sa.ForeignKey("listing_photos.id"),
            nullable=False,
            unique=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("demo_asset_photos")
    op.drop_table("demo_imports")
    op.drop_table("calendar_entries")
