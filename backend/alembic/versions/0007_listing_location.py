"""Optional owner coordinates and durable autocomplete budget; no backfill.

Revision ID: 0007_listing_location
Revises: 0006_listing_categories
"""

import sqlalchemy as sa

from alembic import op

revision = "0007_listing_location"
down_revision = "0006_listing_categories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("listings", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("listings", sa.Column("longitude", sa.Float(), nullable=True))
    op.create_check_constraint(
        "listing_coordinate_pair",
        "listings",
        "(latitude IS NULL AND longitude IS NULL) OR "
        "(latitude IS NOT NULL AND longitude IS NOT NULL AND "
        "latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180)",
    )
    op.create_table(
        "location_provider_budget",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("requests", sa.Integer(), nullable=False),
        sa.Column("recent_requests", sa.JSON(), nullable=False),
        sa.Column("host_requests", sa.JSON(), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("id = 1", name="location_budget_singleton"),
    )
    op.execute(
        "INSERT INTO location_provider_budget (id, day, requests, recent_requests, host_requests) VALUES (1, CURRENT_DATE, 0, '[]', '{}')"
    )


def downgrade() -> None:
    op.drop_table("location_provider_budget")
    op.drop_constraint("listing_coordinate_pair", "listings", type_="check")
    op.drop_column("listings", "longitude")
    op.drop_column("listings", "latitude")
