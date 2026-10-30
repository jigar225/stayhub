"""Offline release tests: real lock/archive/TLS logic; AWS/Docker/systemd stubbed."""

import fcntl
import importlib.util
import io
import json
import os
import shutil
import ssl
import subprocess
import tarfile
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[2]
DEPLOY = PROJECT / "infra/deploy"


def module(name):
    spec = importlib.util.spec_from_file_location(name, DEPLOY / f"{name}.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


receiver, packager, probe = (
    module(name) for name in ["receive", "package", "verify-https"]
)


class HealthcheckTests(unittest.TestCase):
    def test_compose_healthcheck_is_valid_python_and_sends_http(self):
        config = json.loads(
            subprocess.check_output(
                [
                    "docker",
                    "compose",
                    "-f",
                    str(DEPLOY / "compose.yaml"),
                    "config",
                    "--no-env-resolution",
                    "--format",
                    "json",
                ],
                env=os.environ | {"BACKEND_IMAGE": "example.invalid/backend:test"},
                text=True,
            )
        )
        code = compile(
            config["services"]["api"]["healthcheck"]["test"][-1], "healthcheck", "exec"
        )
        with patch("socket.socket") as factory:
            factory.return_value.recv.return_value = b"HTTP/1.1 200 OK\r\n"
            exec(code, {})
            factory.return_value.sendall.assert_called_once_with(
                b"GET /ready HTTP/1.0\r\nHost: localhost\r\n\r\n"
            )
            factory.return_value.recv.return_value = b"HTTP/1.1 503 Unavailable\r\n"
            with self.assertRaises(AssertionError):
                exec(code, {})


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.frontend = self.root / "frontend"
        self.frontend.mkdir()
        (self.frontend / "index.html").write_text("test SPA")
        self.archive = self.root / "release.tar.gz"
        self.digest = packager.package(PROJECT, self.frontend, self.archive)
        self.release = "a" * 40

    def tearDown(self):
        self.temp.cleanup()

    def test_deterministic_assets_and_license_manifest(self):
        second = self.root / "second.tar.gz"
        self.assertEqual(self.digest, packager.package(PROJECT, self.frontend, second))
        output = self.root / "out"
        output.mkdir()
        receiver.extract_verified(self.archive, output)
        manifest = json.loads((output / "demo/assets/manifest.json").read_text())
        self.assertEqual(len(manifest["assets"]), 5)
        self.assertTrue(all(a["license_url"] for a in manifest["assets"]))

    def test_archive_rejects_path_escape_and_links(self):
        for name, kind in [
            ("../escape", tarfile.REGTYPE),
            ("frontend/link", tarfile.SYMTYPE),
        ]:
            archive = self.root / "bad.tar.gz"
            with tarfile.open(archive, "w:gz") as tar:
                info = tarfile.TarInfo(name)
                info.type = kind
                tar.addfile(info, io.BytesIO())
            with self.assertRaises(ValueError):
                receiver.extract_verified(archive, self.root / "out")

    def test_lock_precedes_download(self):
        host = self.root / "host"
        host.mkdir()
        with (host / "deploy.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with patch.object(receiver.subprocess, "run") as run:
                with self.assertRaises(BlockingIOError):
                    receiver.receive(host, self.release, self.digest, "bucket")
                run.assert_not_called()
        self.assertFalse((host / "releases").exists())

    def test_digest_failure_never_promotes(self):
        host = self.root / "host"

        def download(args, **kwargs):
            shutil.copyfile(self.archive, args[4])

        with patch.object(receiver.subprocess, "run", side_effect=download):
            with self.assertRaises(ValueError):
                receiver.receive(host, self.release, "0" * 64, "bucket")
        self.assertFalse((host / "releases" / self.release).exists())

    def test_active_retry_and_previous_directory_immutable(self):
        host = self.root / "host"
        calls = []

        def run(args, **kwargs):
            calls.append(args)
            if args[0] == "aws":
                shutil.copyfile(self.archive, args[4])

        with patch.object(receiver.subprocess, "run", side_effect=run):
            receiver.receive(host, self.release, self.digest, "bucket")
            final = host / "releases" / self.release
            (host / "current").symlink_to(final)
            before = {
                p.relative_to(final): p.read_bytes()
                for p in final.rglob("*")
                if p.is_file()
            }
            (host / "config.json").write_text(json.dumps({"ip": "example.invalid"}))
            calls.clear()
            receiver.receive(host, self.release, self.digest, "bucket")
            self.assertEqual(calls[0][0], "python3")
            self.assertEqual(len(calls), 1)
            with self.assertRaises(ValueError):
                receiver.receive(host, self.release, "0" * 64, "bucket")
            (host / "current").unlink()
            with self.assertRaises(ValueError):
                receiver.receive(host, self.release, self.digest, "bucket")
            self.assertEqual(
                before,
                {
                    p.relative_to(final): p.read_bytes()
                    for p in final.rglob("*")
                    if p.is_file()
                },
            )


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "host"
        self.root.mkdir()
        self.www = self.base / "www"
        (self.www / "releases").mkdir(parents=True)
        self.nginx = self.base / "nginx.conf"
        self.nginx.write_text("original nginx")
        self.bin = self.base / "bin"
        self.bin.mkdir()
        for name in ["flock", "nginx", "systemctl", "certbot"]:
            path = self.bin / name
            path.write_text("#!/bin/sh\nexit 0\n")
            path.chmod(0o755)
        aws = self.bin / "aws"
        aws.write_text("""#!/bin/sh
case "$*" in
 *get-login-password*) echo password ;;
 *db-secret*) echo '{"username":"test","password":"not-a-real-secret"}' ;;
 *) echo '{"JWT_SECRET":"test-only-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"}' ;;
esac
""")
        aws.chmod(0o755)
        docker = self.bin / "docker"
        docker.write_text("""#!/bin/sh
printf '%s\\n' "$BACKEND_IMAGE $*" >> "$STAYHUB_ROOT/docker.log"
if [ -f "$STAYHUB_ROOT/fail-all-up" ]; then
 case "$*" in *"up -d"*) exit 1 ;; esac
fi
if [ -f "$STAYHUB_ROOT/fail-up" ]; then
 case "$*" in *"up -d"*) rm "$STAYHUB_ROOT/fail-up"; exit 1 ;; esac
fi
exit 0
""")
        docker.chmod(0o755)
        key, cert = self.base / "key.pem", self.base / "cert.pem"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(key),
                "-out",
                str(cert),
                "-days",
                "1",
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        outer = self

        class API(BaseHTTPRequestHandler):
            def do_GET(self):
                active = (outer.www / "current").resolve()
                bad = (active / "bad").exists()
                if self.path == "/api/ready":
                    status, data = (
                        200,
                        b"<html>SPA</html>" if bad else b'{"status":"ready"}',
                    )
                elif self.path == "/api/v1/auth/me":
                    status, data = 401, b'{"error":{"code":"unauthenticated"}}'
                else:
                    status, data = 200, b"<html>SPA</html>"
                self.send_response(status)
                self.send_header(
                    "Content-Type",
                    "text/html" if bad or self.path == "/" else "application/json",
                )
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), API)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        self.server.socket = ctx.wrap_socket(self.server.socket, server_side=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = f"localhost:{self.server.server_port}"
        (self.root / "config.json").write_text(
            json.dumps(
                dict(
                    ip=self.origin,
                    email="test@example.org",
                    image="registry/backend",
                    db_host="unused",
                    db_secret="db-secret",
                    app_secret="app-secret",
                    photos="unused",
                )
            )
        )
        self.env = os.environ | {
            "PATH": str(self.bin) + ":" + os.environ["PATH"],
            "STAYHUB_ROOT": str(self.root),
            "STAYHUB_WWW": str(self.www),
            "STAYHUB_NGINX_CONFIG": str(self.nginx),
            "STAYHUB_CERTBOT": str(self.bin / "certbot"),
            "STAYHUB_LOCK_FD": "9",
            "SSL_CERT_FILE": str(cert),
            "STAYHUB_PROBE_ATTEMPTS": "1",
            "STAYHUB_PROBE_DELAY": "0",
        }

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def release(self, sha, bad=False):
        target = self.root / "releases" / sha
        target.mkdir(parents=True)
        shutil.copytree(DEPLOY, target / "deploy")
        shutil.copytree(PROJECT / "demo/assets", target / "demo/assets")
        (target / "frontend").mkdir()
        (target / "frontend/index.html").write_text("SPA")
        if bad:
            (target / "frontend/bad").write_text("bad")
        result = subprocess.run(
            ["bash", str(target / "deploy/release.sh"), sha],
            check=False,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertNotIn("not-a-real-secret", result.stdout + result.stderr)
        return result

    def test_success_verifies_real_tls_api(self):
        result = self.release("a" * 40)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Public HTTPS readiness", result.stdout)
        self.assertEqual((self.root / "current").resolve().name, "a" * 40)
        self.assertIn("X-Forwarded-For $remote_addr", self.nginx.read_text())

    def test_spa_fallback_fails_and_restores_previous(self):
        self.assertEqual(self.release("a" * 40).returncode, 0)
        previous_config = self.nginx.read_bytes()
        result = self.release("b" * 40, bad=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("recovery verified", result.stdout, result.stdout + result.stderr)
        self.assertEqual((self.root / "current").resolve().name, "a" * 40)
        self.assertEqual((self.www / "current").resolve().name, "a" * 40)
        self.assertEqual(self.nginx.read_bytes(), previous_config)
        self.assertIn(
            "registry/backend:" + "a" * 40,
            (self.root / "docker.log").read_text().splitlines()[-1],
        )

    def test_seed_is_explicit_and_repeatable_with_readonly_assets(self):
        self.assertEqual(self.release("a" * 40).returncode, 0)
        self.assertNotIn("app.seed", (self.root / "docker.log").read_text())
        aws = self.bin / "aws"
        fields = {"JWT_SECRET": "x" * 40}
        fields.update(
            {
                f"SEED_{role}_{field}": "test-only-value"
                for role in ["GUEST", "HOST", "ADMIN"]
                for field in ["NAME", "EMAIL", "PASSWORD"]
            }
        )
        aws.write_text(
            '#!/bin/sh\ncase "$*" in\n *db-secret*) echo \'{"username":"test","password":"secret"}\' ;;\n *) echo \''
            + json.dumps(fields)
            + "' ;;\nesac\n"
        )
        for _ in range(2):
            result = subprocess.run(
                ["bash", str(self.root / "current/deploy/seed.sh")],
                check=False,
                env=self.env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("test-only-value", result.stdout + result.stderr)
        log = (self.root / "docker.log").read_text()
        self.assertEqual(log.count("python -m app.seed\n"), 2)
        self.assertEqual(log.count("python -m app.seed_content"), 2)
        self.assertIn("/demo-content:ro", log)

    def test_container_start_failure_recovers(self):
        self.assertEqual(self.release("a" * 40).returncode, 0)
        (self.root / "fail-up").touch()
        result = self.release("c" * 40)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("recovery verified", result.stdout, result.stdout + result.stderr)
        self.assertEqual((self.root / "current").resolve().name, "a" * 40)

    def test_recovery_failure_is_reported(self):
        self.assertEqual(self.release("a" * 40).returncode, 0)
        (self.root / "fail-all-up").touch()
        result = self.release("e" * 40)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RECOVERY FAILED", result.stdout)
        self.assertNotIn("recovery verified", result.stdout)

    def test_untrusted_tls_fails_release(self):
        self.env.pop("SSL_CERT_FILE")
        result = self.release("f" * 40)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "current").exists())
        self.assertNotIn("Deployed", result.stdout)

    def test_first_release_failure_does_not_claim_success(self):
        # GNU readlink -f succeeds even when the final path component is missing.
        readlink = self.bin / "readlink"
        readlink.write_text(
            "#!/usr/bin/env python3\nimport os,sys\nprint(os.path.realpath(sys.argv[-1]))\n"
        )
        readlink.chmod(0o755)
        result = self.release("d" * 40, bad=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "current").exists())
        self.assertEqual(self.nginx.read_text(), "original nginx")
        self.assertIn("down", (self.root / "docker.log").read_text())
        self.assertIn("First release stopped", result.stdout)
        self.assertNotIn("RECOVERY FAILED", result.stdout)
        self.assertFalse((self.www / "current").is_symlink())


if __name__ == "__main__":
    unittest.main(verbosity=2)
