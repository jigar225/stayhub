"""Read-only local V1 preservation evidence; emits hashes, never credentials."""

import json
from pathlib import Path
import subprocess
import sys


def main() -> None:
    phase = sys.argv[1]
    if phase not in {"before", "after"}:
        raise ValueError("Expected before or after")
    code = '''import json, hashlib
from sqlalchemy import text
from app.db import get_engine
from app.config import get_settings
from app.storage import s3_client
from app.main import app
names = ['users', 'user_roles', 'listings', 'listing_photos',
    'cancellation_policies', 'calendar_entries', 'demo_imports',
    'demo_asset_photos', 'reservations', 'payments', 'refunds', 'payouts',
    'event_log', 'idempotency_records']
with get_engine().connect() as connection:
    data = {
        name: sorted(hashlib.sha256(row.encode()).hexdigest()
            for row in connection.execute(text(
                'SELECT row_to_json(t)::text FROM ' + name + ' t')).scalars())
        for name in names
    }
    offset = connection.scalar(text(
        'SELECT offset_seconds FROM app_clock WHERE id=1'))
objects = sorted(hashlib.sha256(json.dumps(obj, sort_keys=True,
    default=str).encode()).hexdigest()
    for page in s3_client().get_paginator('list_objects_v2').paginate(
        Bucket=get_settings().s3_bucket)
    for obj in page.get('Contents', []))
print(json.dumps({'data': data, 'objects': objects,
    'offset_seconds': offset, 'openapi': app.openapi()}))
'''
    run = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "uv", "run", "--frozen",
         "python", "-c", code],
        capture_output=True, text=True, check=True,
    )
    value = json.loads(run.stdout)
    root = Path("evidence/m6")
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{phase}.json").write_text(json.dumps(value, indent=2) + "\n")
    if phase == "before":
        print("Captured main baseline row/object hashes and clock; no records changed.")
        return
    before = json.loads((root / "before.json").read_text())
    result = {
        "baseline_rows": {
            name: {
                "before": len(rows), "after": len(value["data"][name]),
                "preserved": set(rows) <= set(value["data"][name]),
            }
            for name, rows in before["data"].items()
        },
        "baseline_objects_preserved": set(before["objects"]) <= set(value["objects"]),
        "main_clock_offset_seconds": value["offset_seconds"],
        "openapi_unchanged": before["openapi"] == value["openapi"],
    }
    (root / "preservation.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    assert all(row["preserved"] for row in result["baseline_rows"].values())
    assert result["baseline_objects_preserved"]
    assert result["main_clock_offset_seconds"] == 0
    assert result["openapi_unchanged"]


if __name__ == "__main__":
    main()
