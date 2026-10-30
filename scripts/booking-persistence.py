"""Real HTTP M4 reconciliation and ordinary-restart persistence proof.

Creates and retains its own accounts/listing/photos/reservations. Never resets
volumes, changes development business time or edits another user's records.
No credentials or quote tokens are written to evidence.
"""
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import secrets
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4

BASE = "http://localhost:5173"
OUT = Path("evidence/m4")


def call(path, body=None, token=None, method=None, key=None, expected=200):
    headers = {"Origin": BASE}
    if token:
        headers["Authorization"] = "Bearer " + token
    if body is not None:
        headers["Content-Type"] = "application/json"
    if key:
        headers["Idempotency-Key"] = key
    request = urllib.request.Request(
        BASE + "/api/v1" + path,
        headers=headers,
        data=json.dumps(body).encode() if body is not None else None,
        method=method or ("POST" if body is not None else "GET"),
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            assert response.status == expected, (path, response.status, expected)
            return json.load(response)
    except urllib.error.HTTPError as error:
        result = json.load(error)
        if error.code == 429 and expected != 429:
            # Respect existing auth throttles across independently run smoke checks.
            delay = min(60, max(1, int(error.headers.get("Retry-After", "1"))))
            print(f"Auth throttle: waiting {delay}s before retrying the same HTTP request", flush=True)
            time.sleep(delay)
            return call(path, body, token, method, key, expected)
        assert error.code == expected, (path, error.code, result.get("error", {}).get("code"))
        return result


def account(name, host=False):
    password = secrets.token_urlsafe(24)
    email = "m4-" + secrets.token_hex(10) + "@example.com"
    call("/auth/register", {"name": name, "email": email, "password": password}, expected=201)
    result = call("/auth/login", {"email": email, "password": password})
    token = result["access_token"]
    if host:
        call("/me/host-role", token=token, method="POST")
    return token


def create_listing(token):
    listing = call("/host/listings", {}, token, expected=201)["listing"]
    path = "/host/listings/" + listing["id"]
    policy = call("/host/cancellation-policies", token=token)["items"]
    policy = next(row for row in policy if row["name"] == "Moderate")
    listing = call(path, {
        "version": listing["version"], "title": "Fictional M4 persistence review stay",
        "description": "Fictional isolated review listing with illustrative licensed photos.",
        "destination": "M4 Review", "address": "Fictional review address",
        "property_type": "apartment", "timezone": "Europe/Lisbon",
        "capacity": 2, "bedrooms": 1, "beds": 1, "baths": 1,
        "amenities": ["Kitchen"], "house_rules": ["Quiet after 23:00"],
        "nightly_minor": 12800, "cleaning_minor": 3500,
        "policy_id": policy["id"], "booking_mode": "request",
        "check_in_time": "15:00", "check_out_time": "11:00",
    }, token, "PATCH")["listing"]
    manifest_path = Path("demo/assets/manifest.json")
    manifest = json.loads(manifest_path.read_text())
    for asset in manifest["assets"][:5]:
        content = (manifest_path.parent / asset["file"]).read_bytes()
        assert hashlib.sha256(content).hexdigest() == asset["sha256"]
        intent = call(path + "/photos/upload-intents", {
            "content_type": "image/jpeg", "bytes": len(content),
        }, token, expected=201)
        upload = intent["upload"]
        request = urllib.request.Request(upload["url"], data=content,
                                         headers=upload["headers"], method=upload["method"])
        with urllib.request.urlopen(request, timeout=30) as response:
            assert response.status in (200, 204)
        listing = call(path + "/photos/" + intent["photo_id"] + "/complete", {}, token)["listing"]
    return call(path + "/publish", {"version": listing["version"]}, token)["listing"]


def safe_ledger(ids):
    # UUIDs came from authenticated API results; pass code as an argv item, never a shell string.
    code = '''import json
from sqlalchemy import text
from app.db import get_engine
ids = %r
with get_engine().connect() as c:
    result = {}
    for table in ['reservations','payments','refunds','calendar_entries']:
        column = 'id' if table == 'reservations' else 'reservation_id'
        rows = c.execute(text('SELECT row_to_json(t) FROM '+table+' t WHERE '+column+'::text = ANY(:ids)'), {'ids':ids}).scalars().all()
        result[table] = sorted(rows, key=lambda r:str(r['id']))
    targets = ids + [r['id'] for table in ['payments','refunds'] for r in result[table]]
    result['event_log'] = sorted(c.execute(text('SELECT row_to_json(t) FROM event_log t WHERE target_id::text = ANY(:ids)'), {'ids':targets}).scalars().all(), key=lambda r:str(r['id']))
    result['idempotency_hashes'] = sorted(c.execute(text("SELECT row_to_json(t)::text FROM idempotency_records t WHERE response_body->'reservation'->>'id' = ANY(:ids)"), {'ids':ids}).scalars().all())
    import hashlib
    result['idempotency_hashes'] = [hashlib.sha256(r.encode()).hexdigest() for r in result['idempotency_hashes']]
print(json.dumps(result, sort_keys=True))
''' % ids
    run = subprocess.run(["docker", "compose", "exec", "-T", "api", "uv", "run", "--frozen", "python", "-c", code],
                         check=True, capture_output=True, text=True)
    return json.loads(run.stdout)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    host = account("M4 persistence host", host=True)
    other = account("M4 unrelated host", host=True)
    guest = account("M4 persistence guest")
    listing = create_listing(host)
    path = "/host/listings/" + listing["id"]
    start = datetime.now(UTC).date() + timedelta(days=380)
    records = []
    for index, decision in enumerate(["accept", "decline", "instant"]):
        if decision == "instant":
            listing = call(path, {"version": listing["version"], "booking_mode": "instant"}, host, "PATCH")["listing"]
        day = start + timedelta(days=index * 10)
        dates = {"listing_id": listing["id"], "check_in": str(day),
                 "check_out": str(day + timedelta(days=5)), "guests": 2}
        quote = call("/booking-quotes", dates)["quote"]
        key, payload = str(uuid4()), {"quote_token": quote["quote_token"]}
        first = call("/reservations", payload, guest, key=key, expected=201)
        reservation = first["reservation"]
        assert reservation["state"] == ("confirmed" if decision == "instant" else "pending")
        assert reservation["price"]["total_minor"] == 76950
        assert reservation["host_fee_minor"] == 2025 and reservation["host_entitlement_minor"] == 65475
        assert call("/reservations", payload, guest, key=key, expected=201) == first
        rid = reservation["id"]
        call("/host/reservations/" + rid + "/accept", {}, other, key=str(uuid4()), expected=404)
        call("/reservations/" + rid, token=other, expected=404)
        occupied = call("/listings/" + listing["id"] + "/availability?" + urllib.parse.urlencode({
            "start": dates["check_in"], "end": dates["check_out"],
        }))["unavailable"]
        assert occupied
        if decision != "instant":
            body = {} if decision == "accept" else {"reason": "Isolated M4 review decline"}
            decision_key = str(uuid4())
            terminal = call("/host/reservations/" + rid + "/" + decision, body, host, key=decision_key)
            assert call("/host/reservations/" + rid + "/" + decision, body, host, key=decision_key) == terminal
            reservation = terminal["reservation"]
            assert call("/reservations", payload, guest, key=key, expected=201) == first
        if decision == "decline":
            assert reservation["state"] == "declined" and reservation["refund"]["amount_minor"] == 76950
            assert reservation["host_entitlement_minor"] == reservation["platform_entitlement_minor"] == 0
            assert call("/booking-quotes", dates)["quote"]["total_minor"] == 76950
        records.append(reservation)
    listing = call(path, {"version": listing["version"], "title": "Fictional M4 host-edited review stay"}, host, "PATCH")["listing"]
    call(path + "/unlist", {"version": listing["version"]}, host)
    call("/listings/" + listing["id"], expected=404)
    before = {r["id"]: call("/reservations/" + r["id"], token=guest)["reservation"] for r in records}
    photo_hashes = {}
    for rid, record in before.items():
        assert record["listing_snapshot"]["title"] == "Fictional M4 persistence review stay"
        assert record["policy"]["definition"]
        photos = call("/reservations/" + rid + "/photos", token=guest)["items"]
        assert len(photos) == 5
        photo_hashes[rid] = []
        for photo in photos:
            with urllib.request.urlopen(photo["url"], timeout=20) as response:
                photo_hashes[rid].append(hashlib.sha256(response.read()).hexdigest())
    ids = sorted(before)
    ledger_before = safe_ledger(ids)
    assert len(ledger_before["payments"]) == 3 and len(ledger_before["refunds"]) == 1
    assert sum(r["amount_minor"] for r in ledger_before["payments"]) == 230850
    assert sum(r["amount_minor"] for r in ledger_before["refunds"]) == 76950
    assert len(ledger_before["event_log"]) == 9
    subprocess.run(["docker", "compose", "restart", "db", "storage", "api", "frontend", "expiry-worker"], check=True)
    deadline = time.monotonic() + 90
    while True:
        try:
            with urllib.request.urlopen("http://localhost:8000/ready", timeout=5) as response:
                if response.status == 200:
                    break
        except (OSError, urllib.error.URLError):
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError("Services did not recover after ordinary restart")
        time.sleep(1)
    while True:
        try:
            after = {rid: call("/reservations/" + rid, token=guest)["reservation"] for rid in ids}
            assert before == after
            ledger_after = safe_ledger(ids)
            assert ledger_before == ledger_after
            for rid in ids:
                photos = call("/reservations/" + rid + "/photos", token=guest)["items"]
                hashes = []
                for photo in photos:
                    with urllib.request.urlopen(photo["url"], timeout=20) as response:
                        hashes.append(hashlib.sha256(response.read()).hexdigest())
                assert hashes == photo_hashes[rid]
            break
        except (OSError, urllib.error.URLError, ValueError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(1)
    (OUT / "reconciliation.json").write_text(json.dumps(ledger_after, indent=2) + "\n")
    result = {"reservation_codes": [r["code"] for r in records], "reservation_ids": ids,
              "states": [r["state"] for r in records], "payment_rows": 3, "refund_rows": 1,
              "charge_total_minor": 230850, "refund_total_minor": 76950,
              "retained_host_entitlement_minor": sum(r["host_entitlement_minor"] for r in records),
              "retained_platform_entitlement_minor": sum(r["platform_entitlement_minor"] for r in records),
              "event_rows": len(ledger_after["event_log"]), "restart_rows_identical": True,
              "party_photos_after_unlisting_identical": True, "existing_data_deleted": False}
    (OUT / "persistence.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    print("PASS: request accept/decline and instant; full refund; replay; other-host denial; immutable snapshots/unlisted party photos; all financial/event/occupancy rows survive ordinary restart.")


if __name__ == "__main__":
    main()
