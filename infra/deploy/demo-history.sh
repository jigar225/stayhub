#!/bin/bash
# Explicit demo data import, never invoked by a deployment. Default: dry-run.
set -euo pipefail
if [[ $# -gt 1 || ($# -eq 1 && "$1" != '--apply') ]]; then
  echo 'Usage: demo-history.sh [--apply]' >&2; exit 2
fi
root=${STAYHUB_ROOT:-/opt/stayhub}
exec 9>"$root/deploy.lock"
flock -n 9 || { echo 'A deployment/import is running'; exit 1; }
cd "$(readlink -f "$root/current")"
python3 deploy/runtime-env.py
export STAYHUB_ROOT="$root"
export BACKEND_IMAGE=$(cat image.env)
docker compose -p stayhub -f deploy/compose.yaml run --rm --no-deps \
  -v "$PWD/demo:/demo-content:ro" api uv run --frozen python -m app.demo_history "$@"
