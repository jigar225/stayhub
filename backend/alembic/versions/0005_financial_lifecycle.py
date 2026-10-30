"""Partial refunds, payout backfill and forward-only shared business clock."""

import sqlalchemy as sa

from alembic import op

revision = "0005_financial_lifecycle"
down_revision = "0004_bookings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE reservations DROP CONSTRAINT reservation_state, DROP CONSTRAINT reservation_entitlements"
    )
    op.execute("ALTER TABLE reservations ALTER COLUMN state TYPE varchar(24)")
    op.add_column(
        "reservations",
        sa.Column(
            "financial_version", sa.Integer(), nullable=False, server_default="1"
        ),
    )
    op.add_column(
        "reservations",
        sa.Column(
            "effective_host_fee_minor", sa.Integer(), nullable=False, server_default="0"
        ),
    )
    op.add_column("reservations", sa.Column("cancelled_at", sa.DateTime(timezone=True)))
    op.execute(
        "UPDATE reservations SET effective_host_fee_minor = CASE WHEN state = 'declined' THEN 0 ELSE host_fee_minor END"
    )
    op.create_check_constraint(
        "reservation_state",
        "reservations",
        "state IN ('pending','confirmed','checked_in','completed','declined','cancelled_by_guest','cancelled_by_host')",
    )
    op.create_check_constraint(
        "reservation_entitlements",
        "reservations",
        "financial_version >= 1 AND ((state IN ('pending','confirmed','checked_in','completed') AND effective_host_fee_minor = host_fee_minor AND host_entitlement_minor = subtotal_minor - host_fee_minor AND platform_entitlement_minor = guest_fee_minor + host_fee_minor) OR (state IN ('declined','cancelled_by_host') AND effective_host_fee_minor = 0 AND host_entitlement_minor = 0 AND platform_entitlement_minor = 0) OR (state = 'cancelled_by_guest' AND host_entitlement_minor >= 0 AND host_entitlement_minor + effective_host_fee_minor BETWEEN 0 AND nights_minor AND effective_host_fee_minor = ((host_entitlement_minor + effective_host_fee_minor) * 3::bigint + 50) / 100 AND platform_entitlement_minor BETWEEN effective_host_fee_minor AND guest_fee_minor + effective_host_fee_minor))",
    )
    op.drop_constraint("refund_matches_original_charge", "refunds", type_="foreignkey")
    op.add_column("refunds", sa.Column("original_charge_minor", sa.Integer()))
    op.execute(
        "UPDATE refunds SET original_charge_minor = payments.amount_minor FROM payments WHERE refunds.payment_id = payments.id"
    )
    op.alter_column("refunds", "original_charge_minor", nullable=False)
    op.create_foreign_key(
        "refund_matches_original_charge",
        "refunds",
        "payments",
        ["payment_id", "reservation_id", "original_charge_minor"],
        ["id", "reservation_id", "amount_minor"],
    )
    op.drop_constraint("refund_money", "refunds", type_="check")
    op.create_check_constraint(
        "refund_money",
        "refunds",
        "amount_minor >= 0 AND amount_minor <= original_charge_minor AND nights_minor >= 0 AND cleaning_minor >= 0 AND guest_fee_minor >= 0 AND amount_minor = nights_minor + cleaning_minor + guest_fee_minor",
    )
    op.execute("""
CREATE TABLE payouts (
	id UUID NOT NULL, 
	reservation_id UUID NOT NULL, 
	host_id UUID NOT NULL, 
	due_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	gross_minor INTEGER NOT NULL, 
	host_fee_minor INTEGER NOT NULL, 
	net_minor INTEGER NOT NULL, 
	status VARCHAR(12) NOT NULL, 
	paid_at TIMESTAMP WITH TIME ZONE, 
	release_operation VARCHAR(80), 
	PRIMARY KEY (id), 
	CONSTRAINT payout_money CHECK (gross_minor >= 0 AND host_fee_minor >= 0 AND net_minor >= 0 AND gross_minor - host_fee_minor = net_minor AND (status <> 'cancelled' OR net_minor = 0)), 
	CONSTRAINT payout_status CHECK (status IN ('held','scheduled','paid','cancelled')), 
	CONSTRAINT payout_release CHECK ((status = 'paid' AND paid_at IS NOT NULL AND release_operation IS NOT NULL AND net_minor > 0) OR (status <> 'paid' AND paid_at IS NULL AND release_operation IS NULL)), 
	UNIQUE (reservation_id), 
	FOREIGN KEY(reservation_id) REFERENCES reservations (id), 
	FOREIGN KEY(host_id) REFERENCES users (id), 
	UNIQUE (release_operation)
)
    """)
    op.execute("""
CREATE INDEX ix_payouts_host_id ON payouts (host_id)
    """)
    op.execute("""
CREATE INDEX ix_payouts_status ON payouts (status)
    """)
    op.execute("""
CREATE INDEX ix_payouts_due_at ON payouts (due_at)
    """)
    op.execute("""
CREATE TABLE app_clock (
	id SERIAL NOT NULL, 
	offset_seconds BIGINT NOT NULL, 
	version INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT clock_forward CHECK (id = 1 AND offset_seconds >= 0 AND version >= 1)
)
    """)
    op.execute("INSERT INTO app_clock (id, offset_seconds, version) VALUES (1,0,1)")
    op.execute("""
        INSERT INTO payouts (id,reservation_id,host_id,due_at,gross_minor,host_fee_minor,net_minor,status)
        SELECT id,id,host_id,scheduled_check_in + interval '24 hours',
          CASE WHEN state='declined' THEN 0 ELSE subtotal_minor END,
          CASE WHEN state='declined' THEN 0 ELSE host_fee_minor END,
          host_entitlement_minor,
          CASE WHEN state='pending' THEN 'held' WHEN state='declined' THEN 'cancelled' ELSE 'scheduled' END
        FROM reservations
    """)


def downgrade() -> None:
    raise RuntimeError(
        "M5 financial history cannot safely be downgraded after partial refunds or payout releases."
    )
