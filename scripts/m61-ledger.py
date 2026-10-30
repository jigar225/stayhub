"""Read-only assertions executed inside the isolated cold-stack API container."""

import json

from sqlalchemy import text

from app.db import get_engine

with get_engine().connect() as connection:
    counts = {
        table: connection.scalar(text("SELECT count(*) FROM " + table))
        for table in [
            "users",
            "listings",
            "listing_photos",
            "demo_imports",
            "demo_asset_photos",
            "reservations",
            "payments",
            "refunds",
            "payouts",
        ]
    }
    assert counts == dict(
        users=3,
        listings=6,
        listing_photos=30,
        demo_imports=6,
        demo_asset_photos=30,
        reservations=2,
        payments=2,
        refunds=1,
        payouts=2,
    ), counts
    rows = [
        dict(row)
        for row in connection.execute(
            text("""
        SELECT r.code, r.state, p.amount_minor AS charge_minor,
            coalesce(f.amount_minor,0) AS refund_minor,
            r.host_entitlement_minor AS host_minor,
            r.platform_entitlement_minor AS platform_minor,
            o.status AS payout_status, o.net_minor AS payout_minor,
            (SELECT count(*) FROM event_log e
                WHERE e.action='payout.paid' AND e.target_id=o.id) AS payout_events
        FROM reservations r JOIN payments p ON p.reservation_id=r.id
        LEFT JOIN refunds f ON f.reservation_id=r.id
        JOIN payouts o ON o.reservation_id=r.id ORDER BY r.code
    """)
        ).mappings()
    ]
    for row in rows:
        assert (
            row["charge_minor"] - row["refund_minor"]
            == row["host_minor"] + row["platform_minor"]
        )
        assert row["payout_minor"] == row["host_minor"]
        assert row["payout_events"] == (1 if row["payout_status"] == "paid" else 0)
    migration = connection.scalar(text("SELECT version_num FROM alembic_version"))
print(json.dumps({"counts": counts, "rows": rows, "migration_head": migration}))
