#!/bin/bash
# Explicit one-time provisioning. Never called by bootstrap, receiver, workflow
# or release.sh. Creates realistic users, hosts and listings with real photos.
set -euo pipefail
root=${STAYHUB_ROOT:-/opt/stayhub}
exec 9>"$root/deploy.lock"
flock -n 9 || { echo 'A deployment/provision is running'; exit 1; }
cd "$(readlink -f "$root/current")"
python3 deploy/runtime-env.py
# Refuse to start until the manifest and every licensed asset verify.
python3 - <<'PY'
import hashlib
import json
from pathlib import Path
manifest_path = Path('demo/provision.json')
if not manifest_path.is_file():
    raise SystemExit('Missing demo/provision.json; nothing was run.')
manifest = json.loads(manifest_path.read_text())
assets_dir = Path('demo/assets').resolve()
for asset in manifest['assets']:
    path = (assets_dir / Path(asset['file']).name).resolve()
    if (not path.is_relative_to(assets_dir) or not asset.get('license_url')
            or path.stat().st_size != asset['bytes']
            or hashlib.sha256(path.read_bytes()).hexdigest() != asset['sha256']):
        raise SystemExit('Licensed asset validation failed; provisioning was not run.')
PY
export STAYHUB_ROOT="$root"
export BACKEND_IMAGE=$(cat image.env)
compose() { docker compose -p stayhub -f deploy/compose.yaml "$@"; }
compose run --rm --no-deps -v "$PWD/demo:/demo-content:ro" -v "$root:/host-output" \
  -e PROVISION_MANIFEST=/demo-content/provision.json \
  -e PROVISION_CREDENTIALS=/host-output/provisioned-credentials.txt \
  api uv run --frozen python -m app.provision_users
echo "Credentials written to $root/provisioned-credentials.txt (mode 600)."
