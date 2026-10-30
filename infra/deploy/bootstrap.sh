#!/bin/bash
set -euo pipefail
dnf install -y docker nginx python3 python3.11 python3.11-pip
systemctl enable --now docker amazon-ssm-agent
install -d -m 700 /opt/stayhub
install -d -m 750 -g nginx /run/stayhub
printf "d /run/stayhub 0750 root nginx -\n" > /etc/tmpfiles.d/stayhub.conf
install -d -m 755 /var/www/acme /var/www/stayhub
python3.11 -m venv /opt/certbot
/opt/certbot/bin/pip install 'certbot==5.8.0'
# AWS CLI v2 is included in the AL2023 AMI. Compose is installed as a pinned plugin.
install -d /usr/local/lib/docker/cli-plugins
curl --fail --location --retry 3 https://github.com/docker/compose/releases/download/v2.40.3/docker-compose-linux-x86_64 -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod 755 /usr/local/lib/docker/cli-plugins/docker-compose
cat > /etc/nginx/nginx.conf <<'NGINX'
events {}
http {
  server {
    listen 80;
    location /.well-known/acme-challenge/ { root /var/www/acme; }
    location / { return 503; }
  }
}
NGINX
systemctl enable --now nginx
cat > /etc/systemd/system/stayhub-cert-renew.service <<'UNIT'
[Unit]
Description=Renew StayHub IP certificate
[Service]
Type=oneshot
ExecStart=/opt/certbot/bin/certbot renew --quiet --deploy-hook "systemctl reload nginx"
UNIT
cat > /etc/systemd/system/stayhub-cert-renew.timer <<'UNIT'
[Unit]
Description=Check short-lived TLS certificate renewal twice daily
[Timer]
OnCalendar=*-*-* 00,12:00:00
RandomizedDelaySec=1800
Persistent=true
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now stayhub-cert-renew.timer
