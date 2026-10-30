"""Capture non-secret runtime hashes and compare additive M3 compatibility."""
import hashlib
import json
from pathlib import Path
import subprocess

runtime_code = '''import hashlib,json
from pathlib import Path
from sqlalchemy import text
from app.db import get_engine
from app.main import app
names=['cancellation_policies','listing_photos','listings','user_roles','users']
with get_engine().connect() as c:
    data={name:sorted(hashlib.sha256(row.encode()).hexdigest() for row in c.execute(text('SELECT row_to_json(t)::text FROM '+name+' t')).scalars()) for name in names}
source={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for root in ['app','tests','alembic'] for p in sorted(Path(root).rglob('*.py'))}
print(json.dumps({'data':data,'openapi':app.openapi(),'source':source},sort_keys=True))
'''
run = subprocess.run(['docker','compose','exec','-T','api','uv','run','--frozen','python','-c',runtime_code],capture_output=True,text=True,check=True)
runtime=json.loads(run.stdout)
out=Path('evidence/m3')
(out/'runtime-after.json').write_text(json.dumps(runtime,indent=2)+'\n')
before=json.loads((out/'data-before.json').read_text())
row_check={name:{'before':len(rows),'after':len(runtime['data'][name]),'baseline_preserved':set(rows)<=set(runtime['data'][name])} for name,rows in before.items()}
old=json.loads((out/'m2-openapi-before.json').read_text())
new=runtime['openapi']
paths_unchanged=all(new['paths'].get(path)==operations for path,operations in old['paths'].items())
schemas_unchanged=all(new['components']['schemas'].get(name)==schema for name,schema in old['components']['schemas'].items())
source_check={name:hashlib.sha256((Path('backend')/name).read_bytes()).hexdigest()==digest for name,digest in runtime['source'].items()}
manifest=json.loads(Path('demo/assets/manifest.json').read_text())
assets={asset['id']:hashlib.sha256((Path('demo/assets')/asset['file']).read_bytes()).hexdigest()==asset['sha256'] for asset in manifest['assets']}
frontend_code = """const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');const result={};function walk(root){for(const name of fs.readdirSync(root)){const p=path.join(root,name);if(fs.statSync(p).isDirectory())walk(p);else result[p]=crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex')}}for(const root of ['src','tests','e2e'])walk(root);console.log(JSON.stringify(result));"""
frontend_run=subprocess.run(['docker','compose','exec','-T','frontend','node','-e',frontend_code],capture_output=True,text=True,check=True)
frontend_source=json.loads(frontend_run.stdout)
frontend_matches=all(hashlib.sha256((Path('frontend')/name).read_bytes()).hexdigest()==digest for name,digest in frontend_source.items())
(out/'frontend-runtime-source.json').write_text(json.dumps(frontend_source,indent=2)+'\n')
result={'frontend_runtime_matches_local':frontend_matches,'frontend_runtime_source_files':len(frontend_source),'baseline_rows' :row_check,'existing_paths_unchanged':paths_unchanged,'existing_schemas_unchanged':schemas_unchanged,'runtime_source_matches_local':all(source_check.values()),'runtime_source_files':len(source_check),'asset_checksums':assets,'new_paths':sorted(set(new['paths'])-set(old['paths']))}
(out/'compatibility.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
assert all(row['baseline_preserved'] for row in row_check.values())
assert paths_unchanged and schemas_unchanged and all(source_check.values()) and all(assets.values()) and frontend_matches
