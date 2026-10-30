"""Read-only M4→M5 migration, financial, API and storage preservation proof."""
import hashlib
import sys
import json
from pathlib import Path
import subprocess

OUT = Path("evidence/m5")
final_check = "--after-checks" in sys.argv
code = '''import json,hashlib
from sqlalchemy import text
from app.db import get_engine
from app.main import app
from app.config import get_settings
from app.storage import s3_client
with get_engine().connect() as c:
    names=['users','user_roles','listings','listing_photos','cancellation_policies','calendar_entries','demo_imports','demo_asset_photos','reservations','payments','refunds','event_log','idempotency_records','payouts','app_clock']
    rows={n:[json.loads(s) for s in c.execute(text('SELECT row_to_json(t)::text FROM '+n+' t')).scalars()] for n in names}
objects=sorted(hashlib.sha256(json.dumps(o,sort_keys=True,default=str).encode()).hexdigest() for p in s3_client().get_paginator('list_objects_v2').paginate(Bucket=get_settings().s3_bucket) for o in p.get('Contents',[]))
print(json.dumps({'rows':rows,'objects':objects,'openapi':app.openapi()}))
'''
run = subprocess.run(["docker", "compose", "exec", "-T", "api", "uv", "run", "--frozen", "python", "-c", code], check=True, capture_output=True, text=True)
after = json.loads(run.stdout)
before = json.loads((OUT / "baseline.json").read_text())
proof = {}
# M5 adds fields; compare every historical field rather than full row hashes.
financial_names = {"reservations", "payments", "refunds", "event_log"}
for name, hashes in before["data_hashes"].items():
    if name in financial_names:
        continue
    current = {hashlib.sha256(json.dumps(r, sort_keys=True).encode()).hexdigest() for r in after["rows"][name]}
    proof[name] = {"baseline":len(hashes), "current":len(current), "preserved":set(hashes) <= current}
for name, rows in before["financial"].items():
    current = {r["id"]:r for r in after["rows"][name]}
    proof[name] = {"baseline":len(rows), "preserved":all(r["id"] in current and all(current[r["id"]].get(k)==v for k,v in r.items()) for r in rows)}
payouts = {r["reservation_id"]:r for r in after["rows"]["payouts"]}
backfill=[]
from datetime import datetime,timedelta
for r in before["financial"]["reservations"]:
    p=payouts[r["id"]]
    expected={"pending":"held","confirmed":"scheduled","declined":"cancelled"}[r["state"]]
    backfill.append(p["status"]==expected and p["paid_at"] is None and datetime.fromisoformat(p["due_at"])==datetime.fromisoformat(r["scheduled_check_in"])+timedelta(hours=24) and p["net_minor"]==r["host_entitlement_minor"])
# State/DTO expansion is expected, all auth/listing/public quote paths stay exact.
allow_paths={p for p in before['openapi']['paths'] if 'reservations' in p or p.endswith('/host/today') or p.endswith('/calendar')}
path_changes=[p for p,v in before['openapi']['paths'].items() if after['openapi']['paths'].get(p)!=v]
result={"baseline_rows":proof,"all_m4_rows_preserved":all(v['preserved'] for v in proof.values()),"payout_backfill_rows":len(backfill),"backfill_correct_no_release":all(backfill),"main_clock_offset_seconds":after['rows']['app_clock'][0]['offset_seconds'],"development_objects_identical":before['objects']==after['objects'],"baseline_development_objects_preserved":set(before['objects'])<=set(after['objects']),"documented_changed_paths":path_changes,"unexpected_changed_paths":sorted(set(path_changes)-allow_paths),"new_paths":sorted(set(after['openapi']['paths'])-set(before['openapi']['paths']))}
(OUT/('preservation-after-checks.json' if final_check else 'preservation.json')).write_text(json.dumps(result,indent=2)+'\n')
# Safe rows omit account/password/session records and quote-bearing contexts.
(OUT/('financial-after-checks.json' if final_check else 'migration-financial-after.json')).write_text(json.dumps({n:after['rows'][n] for n in ['reservations','payments','refunds','payouts','event_log','app_clock']},indent=2)+'\n')
print(json.dumps(result,indent=2))
assert result['all_m4_rows_preserved'] and result['backfill_correct_no_release'] and (result['baseline_development_objects_preserved'] if final_check else result['development_objects_identical']) and result['main_clock_offset_seconds']==0 and not result['unexpected_changed_paths']
