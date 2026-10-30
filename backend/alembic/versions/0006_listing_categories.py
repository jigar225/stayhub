"""Optional host-declared stay categories, preserving every existing listing.

Revision ID: 0006_listing_categories
Revises: 0005_financial_lifecycle
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

from alembic import op

revision = "0006_listing_categories"
down_revision = "0005_financial_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "listings",
        sa.Column(
            "categories", ARRAY(sa.String(20)), nullable=False, server_default="{}"
        ),
    )


def downgrade() -> None:
    op.drop_column("listings", "categories")
