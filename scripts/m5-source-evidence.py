"""Current M5 changed-file inventory and application runtime source parity."""
import hashlib
import json
from pathlib import Path
import subprocess

OUT=Path('evidence/m5')
before=json.loads((OUT/'source-before.json').read_text())
changed=[]
for root in ['backend','frontend','docs','scripts']:
    for p in Path(root).rglob('*'):
        if not p.is_file() or any(x in p.parts for x in ['node_modules','.venv','__pycache__','.mypy_cache','.ruff_cache','dist','test-results','evidence']):continue
        if str(p)=='docs/deployment-plan.md':continue
        if before.get(str(p))!=hashlib.sha256(p.read_bytes()).hexdigest():changed.append(str(p))
changed.extend(['Makefile','README.md','compose.yaml','compose.m5-review.yaml','.env.example'])
(OUT/'changed-files.json').write_text(json.dumps(sorted(set(changed)),indent=2)+'\n')
code="""import hashlib,json
from pathlib import Path
print(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for root in ['app','tests','alembic'] for p in Path(root).rglob('*.py')}))"""
run=subprocess.run(['docker','compose','exec','-T','api','uv','run','--frozen','python','-c',code],check=True,capture_output=True,text=True)
backend=json.loads(run.stdout)
frontcode="""const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');const r={};function walk(root){for(const name of fs.readdirSync(root)){const p=path.join(root,name);if(fs.statSync(p).isDirectory())walk(p);else r[p]=crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex')}}for(const root of ['src','tests','e2e'])walk(root);console.log(JSON.stringify(r));"""
run=subprocess.run(['docker','compose','exec','-T','frontend','node','-e',frontcode],check=True,capture_output=True,text=True)
front=json.loads(run.stdout)
result={'backend_runtime_matches':all(hashlib.sha256((Path('backend')/p).read_bytes()).hexdigest()==h for p,h in backend.items()),'frontend_runtime_matches':all(hashlib.sha256((Path('frontend')/p).read_bytes()).hexdigest()==h for p,h in front.items()),'backend_files':len(backend),'frontend_files':len(front)}
(OUT/'source-parity.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));assert result['backend_runtime_matches'] and result['frontend_runtime_matches']
