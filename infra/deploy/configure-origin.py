"""Idempotent additive HTTPS API vhost; run as root under the deployment lock."""

import argparse
import ipaddress
import json
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path


def configure(config, dry_run=False, refresh_trust=False):
    ip = str(ipaddress.IPv4Address(config["ip"]))
    hostname = "jigar-stayhub-api." + ip.replace(".", "-") + ".sslip.io"
    root = Path("/etc/nginx/stayhub")
    root.mkdir(mode=0o755, exist_ok=True)
    certbot = [
        "/opt/certbot/bin/certbot",
        "certonly",
        "--non-interactive",
        "--agree-tos",
        "--email",
        config["email"],
        "--webroot",
        "-w",
        "/var/www/acme",
        "-d",
        hostname,
        "--cert-name",
        "jigar-stayhub-api",
        "--keep-until-expiring",
    ]
    if not refresh_trust:
        subprocess.run(certbot + (["--dry-run"] if dry_run else []), check=True)
    if dry_run:
        return
    # CloudFront appends the real viewer address to XFF. Trust ONLY connection
    # peers in AWS's origin-facing CloudFront ranges; never trust public clients.
    with urllib.request.urlopen(
        "https://ip-ranges.amazonaws.com/ip-ranges.json", timeout=30
    ) as response:
        ranges = json.load(response)
    cidrs = [
        p["ip_prefix"]
        for p in ranges["prefixes"]
        if p["service"] == "CLOUDFRONT_ORIGIN_FACING"
    ]
    cidrs += [
        p["ipv6_prefix"]
        for p in ranges["ipv6_prefixes"]
        if p["service"] == "CLOUDFRONT_ORIGIN_FACING"
    ]
    if not cidrs:
        raise ValueError("No CloudFront origin-facing ranges")
    trust = "\n".join(
        "set_real_ip_from " + str(ipaddress.ip_network(c)) + ";" for c in cidrs
    )
    proxy = """proxy_set_header Host $host;
      proxy_set_header X-Forwarded-For $remote_addr;
      proxy_set_header X-Real-IP $remote_addr;
      proxy_set_header X-Forwarded-Proto https;
      proxy_set_header Forwarded "";
      add_header Cache-Control "no-store" always;"""
    content = f"""# Managed by StayHub configure-origin.py
server {{
    listen 80;
    server_name {hostname};
    location /.well-known/acme-challenge/ {{ root /var/www/acme; }}
    location / {{ return 301 https://{hostname}$request_uri; }}
}}
server {{
    listen 443 ssl;
    server_name {hostname};
    ssl_certificate /etc/letsencrypt/live/jigar-stayhub-api/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/jigar-stayhub-api/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    client_max_body_size 1m;
    {trust}
    real_ip_header X-Forwarded-For;
    real_ip_recursive off;
    location = /api/ready {{
      proxy_pass http://unix:/run/stayhub/api.sock:/ready;
      {proxy}
    }}
    location = /api {{
      proxy_pass http://unix:/run/stayhub/api.sock;
      {proxy}
    }}
    location /api/ {{
      proxy_pass http://unix:/run/stayhub/api.sock;
      {proxy}
    }}
    location / {{ return 404; }}
}}
"""
    path = root / "api.conf"
    nginx = Path("/etc/nginx/nginx.conf")
    before, old = nginx.read_text(), path.read_text() if path.exists() else None
    include = "include /etc/nginx/stayhub/*.conf;"
    if len(re.findall(r"\bhttp\s*\{", before)) != 1:
        raise ValueError("Expected one nginx http block")
    # Include last so the existing IP vhost remains default for non-SNI clients.
    without = re.sub(r"(?m)^[ \t]*" + re.escape(include) + r"[ \t]*\n?", "", before)
    head, tail = without.rsplit("}", 1)
    nginx.write_text(head + "  " + include + "\n}" + tail)
    path.write_text(content)
    try:
        subprocess.run(["nginx", "-t"], check=True)
        subprocess.run(["systemctl", "reload", "nginx"], check=True)
    except Exception:
        nginx.write_text(before)
        if old is None:
            path.unlink()
        else:
            path.write_text(old)
        subprocess.run(["nginx", "-t"], check=True)
        subprocess.run(["systemctl", "reload", "nginx"], check=True)
        raise
    subprocess.run(["systemctl", "is-active", "stayhub-cert-renew.timer"], check=True)
    if not refresh_trust:
        installed = Path("/opt/stayhub/configure-origin.py")
        if Path(__file__).resolve() != installed.resolve():
            shutil.copyfile(__file__, installed)
            installed.chmod(0o700)
        Path("/etc/systemd/system/jigar-stayhub-origin-trust.service").write_text(
            "[Unit]\nDescription=Refresh AWS CloudFront origin trust ranges\n"
            "[Service]\nType=oneshot\n"
            "ExecStart=/usr/bin/flock -n /opt/stayhub/deploy.lock /usr/bin/python3 /opt/stayhub/configure-origin.py --refresh-trust\n"
        )
        Path("/etc/systemd/system/jigar-stayhub-origin-trust.timer").write_text(
            "[Unit]\nDescription=Daily CloudFront trust range refresh\n"
            "[Timer]\nOnCalendar=daily\nRandomizedDelaySec=1800\nPersistent=true\n"
            "[Install]\nWantedBy=timers.target\n"
        )
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        subprocess.run(
            ["systemctl", "enable", "--now", "jigar-stayhub-origin-trust.timer"],
            check=True,
        )
    print("HTTPS origin configured:", hostname)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--refresh-trust", action="store_true")
    args = parser.parse_args()
    configure(
        json.loads(Path("/opt/stayhub/config.json").read_text()),
        args.dry_run,
        args.refresh_trust,
    )
