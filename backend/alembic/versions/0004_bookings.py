"""Atomic booking, simulated money, idempotency and audited transitions.

Frozen PostgreSQL DDL; preserves all M1–M3 data and the shared occupancy exclusion.
"""

from alembic import op

revision = "0004_bookings"
down_revision = "0003_calendar_demo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE reservations (
	id UUID NOT NULL, 
	code VARCHAR(24) NOT NULL, 
	listing_id UUID NOT NULL, 
	guest_id UUID NOT NULL, 
	host_id UUID NOT NULL, 
	state VARCHAR(12) NOT NULL, 
	reason VARCHAR(500), 
	booking_mode VARCHAR(10) NOT NULL, 
	check_in DATE NOT NULL, 
	check_out DATE NOT NULL, 
	guests INTEGER NOT NULL, 
	timezone VARCHAR(100) NOT NULL, 
	scheduled_check_in TIMESTAMP WITH TIME ZONE NOT NULL, 
	scheduled_check_out TIMESTAMP WITH TIME ZONE NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	request_deadline TIMESTAMP WITH TIME ZONE, 
	listing_snapshot JSON NOT NULL, 
	policy_snapshot JSON NOT NULL, 
	nightly_minor INTEGER NOT NULL, 
	nights_minor INTEGER NOT NULL, 
	cleaning_minor INTEGER NOT NULL, 
	subtotal_minor INTEGER NOT NULL, 
	guest_fee_minor INTEGER NOT NULL, 
	total_minor INTEGER NOT NULL, 
	host_fee_minor INTEGER NOT NULL, 
	host_entitlement_minor INTEGER NOT NULL, 
	platform_entitlement_minor INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT reservation_charge_reference UNIQUE (id, total_minor), 
	CONSTRAINT reservation_state CHECK (state IN ('pending','confirmed','declined')), 
	CONSTRAINT reservation_mode CHECK (booking_mode IN ('instant','request')), 
	CONSTRAINT reservation_dates CHECK (check_in < check_out AND check_out - check_in BETWEEN 1 AND 180), 
	CONSTRAINT reservation_guests CHECK (guests BETWEEN 1 AND 30), 
	CONSTRAINT reservation_schedule CHECK (scheduled_check_out > scheduled_check_in), 
	CONSTRAINT reservation_deadline CHECK ((booking_mode = 'instant' AND request_deadline IS NULL) OR (booking_mode = 'request' AND request_deadline = created_at + interval '24 hours')), 
	CONSTRAINT reservation_money CHECK (nightly_minor >= 0 AND nights_minor >= 0 AND cleaning_minor >= 0 AND subtotal_minor = nights_minor + cleaning_minor AND guest_fee_minor = (subtotal_minor * 14::bigint + 50) / 100 AND total_minor = subtotal_minor + guest_fee_minor AND host_fee_minor = (subtotal_minor * 3::bigint + 50) / 100), 
	CONSTRAINT reservation_entitlements CHECK ((state = 'declined' AND host_entitlement_minor = 0 AND platform_entitlement_minor = 0) OR (state <> 'declined' AND host_entitlement_minor = subtotal_minor - host_fee_minor AND platform_entitlement_minor = guest_fee_minor + host_fee_minor)), 
	CONSTRAINT reservation_distinct_parties CHECK (guest_id <> host_id), 
	UNIQUE (code), 
	FOREIGN KEY(listing_id) REFERENCES listings (id), 
	FOREIGN KEY(guest_id) REFERENCES users (id), 
	FOREIGN KEY(host_id) REFERENCES users (id)
)
    """)
    op.execute("CREATE INDEX ix_reservations_listing_id ON reservations (listing_id)")
    op.execute("CREATE INDEX ix_reservations_state ON reservations (state)")
    op.execute("CREATE INDEX ix_reservations_guest_id ON reservations (guest_id)")
    op.execute(
        "CREATE INDEX ix_reservations_request_deadline ON reservations (request_deadline)"
    )
    op.execute("CREATE INDEX ix_reservations_host_id ON reservations (host_id)")
    op.execute("""
CREATE TABLE payments (
	id UUID NOT NULL, 
	reservation_id UUID NOT NULL, 
	operation_id VARCHAR(80) NOT NULL, 
	amount_minor INTEGER NOT NULL, 
	currency VARCHAR(3) NOT NULL, 
	paid_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT payment_matches_charge FOREIGN KEY(reservation_id, amount_minor) REFERENCES reservations (id, total_minor), 
	CONSTRAINT payment_refund_reference UNIQUE (id, reservation_id, amount_minor), 
	CONSTRAINT payment_money CHECK (amount_minor >= 0 AND currency = 'EUR'), 
	UNIQUE (reservation_id), 
	UNIQUE (operation_id)
)
    """)
    op.execute("""
CREATE TABLE refunds (
	id UUID NOT NULL, 
	payment_id UUID NOT NULL, 
	reservation_id UUID NOT NULL, 
	operation_id VARCHAR(80) NOT NULL, 
	amount_minor INTEGER NOT NULL, 
	nights_minor INTEGER NOT NULL, 
	cleaning_minor INTEGER NOT NULL, 
	guest_fee_minor INTEGER NOT NULL, 
	reason VARCHAR(500) NOT NULL, 
	refunded_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT refund_matches_original_charge FOREIGN KEY(payment_id, reservation_id, amount_minor) REFERENCES payments (id, reservation_id, amount_minor), 
	CONSTRAINT refund_money CHECK (amount_minor >= 0 AND nights_minor >= 0 AND cleaning_minor >= 0 AND guest_fee_minor >= 0 AND amount_minor = nights_minor + cleaning_minor + guest_fee_minor), 
	UNIQUE (payment_id), 
	UNIQUE (reservation_id), 
	FOREIGN KEY(reservation_id) REFERENCES reservations (id), 
	UNIQUE (operation_id)
)
    """)
    op.execute("""
CREATE TABLE idempotency_records (
	id UUID NOT NULL, 
	actor_id UUID NOT NULL, 
	operation VARCHAR(100) NOT NULL, 
	key VARCHAR(128) NOT NULL, 
	fingerprint VARCHAR(64) NOT NULL, 
	status_code INTEGER NOT NULL, 
	response_body JSON NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT idempotency_scope UNIQUE (actor_id, operation, key), 
	FOREIGN KEY(actor_id) REFERENCES users (id)
)
    """)
    op.execute("""
CREATE TABLE event_log (
	id UUID NOT NULL, 
	actor_id UUID, 
	system_identity VARCHAR(40), 
	action VARCHAR(60) NOT NULL, 
	target_type VARCHAR(30) NOT NULL, 
	target_id UUID NOT NULL, 
	before JSON, 
	after JSON NOT NULL, 
	business_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	recorded_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT event_business_identity UNIQUE (action, target_id), 
	CONSTRAINT event_actor CHECK ((actor_id IS NOT NULL AND system_identity IS NULL) OR (actor_id IS NULL AND system_identity IS NOT NULL)), 
	FOREIGN KEY(actor_id) REFERENCES users (id)
)
    """)
    op.execute("CREATE INDEX ix_event_log_target_id ON event_log (target_id)")
    op.create_foreign_key(
        "occupancy_reservation_fk",
        "calendar_entries",
        "reservations",
        ["reservation_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "occupancy_one_per_reservation", "calendar_entries", ["reservation_id"]
    )


def downgrade() -> None:
    op.drop_constraint(
        "occupancy_one_per_reservation", "calendar_entries", type_="unique"
    )
    op.drop_constraint(
        "occupancy_reservation_fk", "calendar_entries", type_="foreignkey"
    )
    op.drop_table("event_log")
    op.drop_table("idempotency_records")
    op.drop_table("refunds")
    op.drop_table("payments")
    op.drop_table("reservations")
