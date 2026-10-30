"""Real Nginx→Unix socket→Uvicorn→auth_attempt integration, isolated containers."""

import json
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]


class ProxyTest(unittest.TestCase):
    def test_spoofed_headers_do_not_change_client_or_reset_rate_limit(self):
        name = "stayhub-proxy-test-" + uuid.uuid4().hex[:10]
        containers = []

        def docker(*args):
            return subprocess.check_output(["docker", *args], text=True).strip()

        docker("network", "create", name)
        docker("volume", "create", name)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                conf = Path(tmp) / "nginx.conf"
                # The public proxy policy matches release.sh: replace, never append XFF.
                conf.write_text("""events {}\nhttp { server { listen 8080;
location /api/ { proxy_pass http://unix:/run/stayhub/api.sock;
proxy_set_header X-Forwarded-For $remote_addr;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-Proto https;
proxy_set_header Forwarded "";
} } }""")
                api = name + "-api"
                containers.append(api)
                docker(
                    "run",
                    "-d",
                    "--name",
                    api,
                    "--network",
                    name,
                    "-v",
                    f"{name}:/run/stayhub",
                    "-v",
                    f"{PROJECT}/backend:/source:ro",
                    "-v",
                    f"{PROJECT}/infra/tests:/tests:ro",
                    "-e",
                    "PYTHONPATH=/source:/tests",
                    "-e",
                    "DATABASE_URL=postgresql://unused",
                    "-e",
                    "JWT_SECRET=" + "x" * 40,
                    "-e",
                    "RATE_LIMIT_ATTEMPTS=2",
                    "-e",
                    "RATE_LIMIT_WINDOW_SECONDS=60",
                    "--entrypoint",
                    "/app/.venv/bin/uvicorn",
                    "stayhub-api:latest",
                    "proxy_app:app",
                    "--uds",
                    "/run/stayhub/api.sock",
                    "--proxy-headers",
                    "--forwarded-allow-ips=*",
                )
                proxy = name + "-nginx"
                containers.append(proxy)
                docker(
                    "run",
                    "-d",
                    "--name",
                    proxy,
                    "--network",
                    name,
                    "--network-alias",
                    "proxy",
                    "-v",
                    f"{name}:/run/stayhub",
                    "-v",
                    f"{conf}:/etc/nginx/nginx.conf:ro",
                    "nginx:1.28-alpine",
                )
                script = """import json, urllib.request, urllib.error, time
results=[]
for spoof in ['1.2.3.4','5.6.7.8','9.10.11.12']:
 req=urllib.request.Request('http://proxy:8080/api/v1/auth/login',data=b'{}',headers={
 'Content-Type':'application/json','Origin':'http://localhost:5173',
 'X-Forwarded-For':spoof,'X-Real-IP':spoof,'Forwarded':'for='+spoof,'X-Forwarded-Proto':'http'})
 for attempt in range(30):
  try:
   response=urllib.request.urlopen(req); break
  except urllib.error.HTTPError as e:
   if e.code==502 and attempt<29: time.sleep(1); continue
   response=e; break
  except OSError:
   if attempt==29: raise
   time.sleep(1)
 results.append([response.status,json.loads(response.read())])
print(json.dumps(results))
"""
                client1 = name + "-client1"
                containers.append(client1)
                docker(
                    "run",
                    "-d",
                    "--name",
                    client1,
                    "--network",
                    name,
                    "python:3.13.9-slim",
                    "sleep",
                    "300",
                )
                result = json.loads(docker("exec", client1, "python", "-c", script))
                self.assertEqual([r[0] for r in result], [200, 200, 429], result)
                self.assertEqual(result[0][1]["client"], result[1][1]["client"])
                self.assertNotIn(result[0][1]["client"], ["1.2.3.4", "5.6.7.8"])
                self.assertEqual(result[0][1]["scheme"], "https")
                # A second real client gets an independent bucket.
                client2 = name + "-client2"
                containers.append(client2)
                docker(
                    "run",
                    "-d",
                    "--name",
                    client2,
                    "--network",
                    name,
                    "python:3.13.9-slim",
                    "sleep",
                    "300",
                )
                second = json.loads(docker("exec", client2, "python", "-c", script))
                self.assertEqual(second[0][0], 200, second)
                self.assertNotEqual(second[0][1]["client"], result[0][1]["client"])
                # Model a trusted CloudFront connection: XFF's rightmost address
                # is appended by CloudFront, preceding viewer values are untrusted.
                peer = json.loads(docker("inspect", client2))[0]["NetworkSettings"][
                    "Networks"
                ][name]["IPAddress"]
                conf.write_text(
                    conf.read_text().replace(
                        "listen 8080;",
                        "listen 8080; set_real_ip_from "
                        + peer
                        + "; real_ip_header X-Forwarded-For; real_ip_recursive off;",
                    )
                )
                docker("exec", proxy, "nginx", "-s", "reload")
                import time

                time.sleep(1)
                trusted = script.replace(
                    "'X-Forwarded-For':spoof",
                    "'X-Forwarded-For':spoof+', 198.51.100.27'",
                )
                forwarded = json.loads(docker("exec", client2, "python", "-c", trusted))
                self.assertEqual([r[0] for r in forwarded], [200, 200, 429], forwarded)
                self.assertEqual(forwarded[0][1]["client"], "198.51.100.27")
                self.assertEqual(forwarded[1][1]["client"], "198.51.100.27")

        finally:
            for container in containers:
                subprocess.run(
                    ["docker", "rm", "-f", container],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            subprocess.run(
                ["docker", "volume", "rm", name], check=False, stdout=subprocess.DEVNULL
            )
            subprocess.run(
                ["docker", "network", "rm", name],
                check=False,
                stdout=subprocess.DEVNULL,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
