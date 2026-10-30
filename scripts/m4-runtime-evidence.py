"""Verify existing data/API preservation and rebuilt runtime source parity."""
import hashlib
import json
from pathlib import Path
import subprocess

OUT = Path("evidence/m4")
code = '''import hashlib,json
from pathlib import Path
from sqlalchemy import text
from app.db import get_engine
from app.main import app
from app import storage
from app.config import get_settings
names=['users','user_roles','listings','listing_photos','cancellation_policies','calendar_entries','demo_imports','demo_asset_photos']
with get_engine().connect() as c:
    data={n:sorted(hashlib.sha256(s.encode()).hexdigest() for s in c.execute(text('SELECT row_to_json(t)::text FROM '+n+' t')).scalars()) for n in names}
with get_engine().connect() as c:
    verified=list(c.execute(text("SELECT id,final_key FROM listing_photos WHERE state='verified' AND final_key IS NOT NULL")))
client=storage.s3_client()
missing=[]
for photo_id,key in verified:
    try: client.head_object(Bucket=get_settings().s3_bucket,Key=key)
    except Exception: missing.append(str(photo_id))
source={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for root in ['app','tests','alembic'] for p in sorted(Path(root).rglob('*.py'))}
print(json.dumps({'data':data,'openapi':app.openapi(),'source':source,'verified_storage':{'checked':len(verified),'missing_photo_ids':missing}},sort_keys=True))
'''
run = subprocess.run(["docker", "compose", "exec", "-T", "api", "uv", "run", "--frozen", "python", "-c", code],
                     check=True, capture_output=True, text=True)
runtime = json.loads(run.stdout)
before = json.loads((OUT / "baseline.json").read_text())
(OUT / "runtime-after.json").write_text(json.dumps(runtime, indent=2) + "\n")
rows = {name: {"before": len(values), "after": len(runtime["data"][name]),
               "baseline_preserved": set(values) <= set(runtime["data"][name])}
        for name, values in before["data"].items()}
exceptions = {"/api/v1/host/today", "/api/v1/host/listings/{listing_id}/calendar"}
paths = {path: runtime["openapi"]["paths"].get(path) == value
         for path, value in before["openapi"]["paths"].items() if path not in exceptions}
# Only the documented calendar union and replaced Today DTO may differ.
schema_exceptions = {"CalendarResponse", "HostTodayResponse"}
schemas = {name: runtime["openapi"]["components"]["schemas"].get(name) == value
           for name, value in before["openapi"]["components"]["schemas"].items()
           if name not in schema_exceptions}
backend_source = {name: hashlib.sha256((Path("backend") / name).read_bytes()).hexdigest() == digest
                  for name, digest in runtime["source"].items()}
frontend_code = """const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');const r={};function walk(root){for(const name of fs.readdirSync(root)){const p=path.join(root,name);if(fs.statSync(p).isDirectory())walk(p);else r[p]=crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex')}}for(const root of ['src','tests','e2e'])walk(root);console.log(JSON.stringify(r));"""
run = subprocess.run(["docker", "compose", "exec", "-T", "frontend", "node", "-e", frontend_code],
                     check=True, capture_output=True, text=True)
frontend_source = json.loads(run.stdout)
(OUT / "frontend-source.json").write_text(json.dumps(frontend_source, indent=2) + "\n")
frontend_matches = all(hashlib.sha256((Path("frontend") / n).read_bytes()).hexdigest() == h
                       for n, h in frontend_source.items())
source_before = json.loads((OUT / "source-before.json").read_text())
changed = []
for root in ["backend", "frontend", "docs", "scripts"]:
    for p in Path(root).rglob("*"):
        # Concurrent deployment planning belongs to another chat, not M4.
        if str(p) == "docs/deployment-plan.md":
            continue
        if not p.is_file() or any(x in p.parts for x in ["node_modules", ".venv", "__pycache__", ".mypy_cache", ".ruff_cache", "dist", "test-results", "evidence"]):
            continue
        if source_before.get(str(p)) != hashlib.sha256(p.read_bytes()).hexdigest():
            changed.append(str(p))
changed.extend(["Makefile", "compose.yaml", "README.md"])
(OUT / "changed-files.json").write_text(json.dumps(sorted(set(changed)), indent=2) + "\n")
result = {"verified_photo_objects": runtime["verified_storage"], "baseline_rows": rows, "existing_paths_compatible": all(paths.values()),
          "unexpected_changed_paths": [p for p, ok in paths.items() if not ok],
          "existing_schemas_compatible": all(schemas.values()),
          "unexpected_changed_schemas": [n for n, ok in schemas.items() if not ok],
          "documented_changes": sorted(exceptions),
          "new_paths": sorted(set(runtime["openapi"]["paths"]) - set(before["openapi"]["paths"])),
          "backend_runtime_source_matches": all(backend_source.values()),
          "frontend_runtime_source_matches": frontend_matches}
(OUT / "compatibility.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
assert all(r["baseline_preserved"] for r in rows.values())
assert all(paths.values()) and all(schemas.values())
assert all(backend_source.values()) and frontend_matches

assert not runtime["verified_storage"]["missing_photo_ids"]
