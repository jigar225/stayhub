#!/bin/bash
set -Eeuo pipefail
root=${STAYHUB_ROOT:-/opt/stayhub}
nginx_config=${STAYHUB_NGINX_CONFIG:-/etc/nginx/nginx.conf}
certbot=${STAYHUB_CERTBOT:-/opt/certbot/bin/certbot}
# Receiver owns the lock from BEFORE download through successful probe/recovery.
: "${STAYHUB_LOCK_FD:?Run through the host-installed receiver}"
flock -n "$STAYHUB_LOCK_FD" || exit 1
release=${1:?Supply commit SHA}
[[ "$release" =~ ^[a-f0-9]{40}$ ]] || exit 2
cd "$root/releases/$release"
test -s "$root/config.json"
python3 deploy/runtime-env.py
read_config() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])' "$root/config.json" "$1"; }
ip=$(read_config ip)
email=$(read_config email)
image=$(read_config image)
registry=${image%%/*}
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin "$registry"
export BACKEND_IMAGE="$image:$release"
export STAYHUB_ROOT="$root"
compose() { docker compose -p stayhub -f deploy/compose.yaml "$@"; }
compose pull
previous=""
if [[ -L "$root/current" && -d "$root/current" && -f "$root/current/image.env" && -f "$root/current/deploy/verify-https.py" ]]; then
  previous=$(readlink -f "$root/current")
fi
backup=$(mktemp "$root/.nginx-backup.XXXXXX")
cp "$nginx_config" "$backup"
rollback() {
  failure=$?
  trap - ERR
  set +e
  echo 'Release failed; recovering previous application. Database migrations are retained.'
  recovery=0
  if [[ -n "$previous" && -f "$previous/image.env" ]]; then
    export BACKEND_IMAGE=$(cat "$previous/image.env")
    docker compose -p stayhub -f "$previous/deploy/compose.yaml" up -d --wait --wait-timeout 180 || recovery=1
  else
    compose down || recovery=1
  fi
  cp "$backup" "$nginx_config" || recovery=1
  nginx -t && systemctl reload nginx || recovery=1
  if [[ -n "$previous" && $recovery == 0 ]]; then
    python3 "$previous/deploy/verify-https.py" "https://$ip" || recovery=1
  fi
  if [[ $recovery != 0 ]]; then echo 'RECOVERY FAILED: inspect host before retrying';
  elif [[ -n "$previous" ]]; then echo 'Previous application recovery verified';
  else echo 'First release stopped; original proxy configuration restored'; fi
  rm -f "$backup"
  exit "$failure"
}
trap rollback ERR
# Migrations must remain compatible with the previous running application.
compose run --rm --no-deps api uv run --frozen alembic upgrade head
compose up -d --wait --wait-timeout 180
"$certbot" certonly --non-interactive --agree-tos --email "$email" \
  --preferred-profile shortlived --webroot -w /var/www/acme \
  --ip-address "$ip" --cert-name stayhub --keep-until-expiring
cat > nginx.conf <<NGINX
user nginx;
events {}
http {
  include /etc/nginx/mime.types;
  default_type application/octet-stream;
  server {
    listen 80;
    server_name $ip;
    location /.well-known/acme-challenge/ { root /var/www/acme; }
    location / { return 301 https://$ip\$request_uri; }
  }
  server {
    listen 443 ssl;
    server_name $ip;
    ssl_certificate /etc/letsencrypt/live/stayhub/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/stayhub/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    client_max_body_size 1m;
    # Uvicorn accepts proxy headers ONLY via this Unix socket; it has no TCP listener.
    location = /api {
      proxy_pass http://unix:/run/stayhub/api.sock;
      proxy_set_header Host \$host;
      proxy_set_header X-Forwarded-For \$remote_addr;
      proxy_set_header X-Forwarded-Proto https;
      proxy_set_header Forwarded "";
    }
    location /api/ {
      proxy_pass http://unix:/run/stayhub/api.sock;
      proxy_set_header Host \$host;
      proxy_set_header X-Forwarded-For \$remote_addr;
      proxy_set_header X-Real-IP \$remote_addr;
      proxy_set_header X-Forwarded-Proto https;
      proxy_set_header Forwarded "";
    }
    location = /api/ready {
      proxy_pass http://unix:/run/stayhub/api.sock:/ready;
      proxy_set_header X-Forwarded-For \$remote_addr;
      proxy_set_header X-Forwarded-Proto https;
      proxy_set_header Forwarded "";
    }
    location / { return 404; }
  }
  include /etc/nginx/stayhub/*.conf;
}
NGINX
printf '%s\n' "$BACKEND_IMAGE" > image.env
cp nginx.conf "$nginx_config"
nginx -t
systemctl reload nginx
if python3 -c 'import json,sys; sys.exit(not json.load(open(sys.argv[1])).get("cdn_origin"))' "$root/config.json"; then
  python3 deploy/configure-origin.py
fi
python3 deploy/verify-https.py "https://$ip"
ln -sfn "$PWD" "$root/current"
trap - ERR
rm -f "$backup"
echo "Deployed $release at https://$ip"
