#!/bin/bash
# Explicit only. Never called by bootstrap, receiver, workflow or release.sh.
set -euo pipefail
root=${STAYHUB_ROOT:-/opt/stayhub}
exec 9>"$root/deploy.lock"
flock -n 9 || { echo 'A deployment/seed is running'; exit 1; }
cd "$(readlink -f "$root/current")"
python3 deploy/runtime-env.py
# Refuse to start either seed until every account input and all licensed files exist.
python3 - "$root/runtime.env" <<'PY'
import sys
import hashlib
import json
from pathlib import Path
values = dict(line.rstrip('\n').split('=', 1) for line in Path(sys.argv[1]).read_text().splitlines() if '=' in line)
required = [f'SEED_{role}_{field}' for role in ['GUEST', 'HOST', 'ADMIN'] for field in ['EMAIL', 'PASSWORD', 'NAME']]
if any(not values.get(key) for key in required):
    raise SystemExit('Set all nine SEED_* values in the application secret first. No values displayed.')
assets = Path('demo/assets').resolve()
for asset in json.loads((assets / 'manifest.json').read_text())['assets']:
    path = (assets / asset['file']).resolve()
    if (not path.is_relative_to(assets) or not asset.get('license_url')
            or path.stat().st_size != asset['bytes']
            or hashlib.sha256(path.read_bytes()).hexdigest() != asset['sha256']):
        raise SystemExit('Licensed asset validation failed; seeds were not run.')
PY
export STAYHUB_ROOT="$root"
export BACKEND_IMAGE=$(cat image.env)
compose() { docker compose -p stayhub -f deploy/compose.yaml "$@"; }
compose run --rm --no-deps api uv run --frozen python -m app.seed
compose run --rm --no-deps -v "$PWD/demo:/demo-content:ro" \
  -e DEMO_CONTENT_MANIFEST=/demo-content/assets/manifest.json \
  api uv run --frozen python -m app.seed_content
