"""Record reproducible hashes of delivered source without touching secrets/artifacts."""
import hashlib
import json
from pathlib import Path

paths = [Path('compose.yaml'), Path('Makefile'), Path('.env.example'), Path('README.md')]
for root in ('backend/app', 'backend/tests', 'backend/alembic', 'frontend/src', 'frontend/tests', 'frontend/e2e'):
    paths.extend(p for p in Path(root).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
paths.extend(Path(p) for p in ('backend/pyproject.toml','backend/uv.lock','frontend/package.json','frontend/package-lock.json','docs/m2-contract.md'))
Path('evidence/m2-source-state.json').write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)},indent=2)+'\n')
print('Recorded hashes of source/contracts/config only; secrets excluded.')
