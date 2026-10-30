"""Isolated regression checks for CDN navigation and publication boundaries."""

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "publish", ROOT / "infra/deploy/publish-frontend.py"
)
publish = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish)


class DeliveryTests(unittest.TestCase):
    def test_navigation_preserves_api_missing_assets_and_unknown_paths(self):
        source = (ROOT / "infra/deploy/navigation.js").read_text()
        cases = {
            "/": "/index.html",
            "/login": "/index.html",
            "/host/listings/abc/edit": "/index.html",
            "/stays/123": "/index.html",
            "/api": "/api",
            "/api/ready": "/api/ready",
            "/assets/missing.js": "/assets/missing.js",
            "/stays/missing.js": "/stays/missing.js",
            "/unknown": "/unknown",
        }
        source += (
            "\nconst cases="
            + json.dumps(cases)
            + """;
for (const [uri, expected] of Object.entries(cases)) {
  if (handler({request:{uri,method:'GET'}}).uri !== expected) throw Error(uri);
  if (handler({request:{uri,method:'POST'}}).uri !== uri) throw Error('POST '+uri);
}
"""
        )
        subprocess.run(["node", "-e", source], check=True)

    def test_failed_asset_upload_does_not_promote_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "assets").mkdir()
            (root / "assets/app-AbCd1234.js").write_text("checked code")
            (root / "index.html").write_text("checked index")
            calls = []

            def aws(*args):
                calls.append(args)
                if "s3://bucket/assets/app-AbCd1234.js" in args:
                    raise RuntimeError("isolated upload failure")
                return ""

            with patch.object(publish, "aws", aws), self.assertRaises(RuntimeError):
                publish.publish(root, "a" * 40, "bucket", "distribution")
            self.assertFalse(any("s3://bucket/index.html" in c for c in calls))

    def test_index_is_last_and_invalidated_without_deleting_old_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "assets").mkdir()
            (root / "assets/app-AbCd1234.js").write_text("checked code")
            (root / "index.html").write_text("checked index")
            calls = []

            def aws(*args):
                calls.append(args)
                return (
                    '{"Invalidation":{"Id":"test"}}'
                    if args[:2] == ("cloudfront", "create-invalidation")
                    else ""
                )

            with patch.object(publish, "aws", aws):
                publish.publish(root, "a" * 40, "bucket", "distribution")
            uploads = [c for c in calls if c[:2] == ("s3", "cp")]
            self.assertIn("s3://bucket/index.html", uploads[-1])
            self.assertIn("no-cache,max-age=0,must-revalidate", uploads[-1])
            self.assertTrue(
                any("public,max-age=31536000,immutable" in c for c in calls)
            )
            self.assertFalse(any("--delete" in c for c in calls))
            self.assertEqual(
                calls[-1][:3], ("cloudfront", "wait", "invalidation-completed")
            )

    def test_corrupted_snapshot_cannot_promote_index(self):
        digest = "b" * 64
        snapshot = f"s3://bucket/releases/{'a' * 40}/{digest}/"
        calls = []

        def aws(*args):
            calls.append(args)
            if args[2].endswith("frontend-release.json"):
                Path(args[3]).write_text(
                    json.dumps(
                        {
                            "release": "a" * 40,
                            "index_sha256": digest,
                            "files": {
                                "assets/app-AbCd1234.js": "c" * 64,
                                "index.html": digest,
                            },
                        }
                    )
                )
            else:
                Path(args[3]).write_text("corrupted content")
            return ""

        with (
            patch.object(publish, "aws", aws),
            self.assertRaisesRegex(ValueError, "checksum"),
        ):
            publish.rollback(snapshot, "bucket", "distribution")
        self.assertTrue(all(c[2].startswith(snapshot) for c in calls))

    def test_origin_include_is_last_idempotent_and_trust_is_scoped(self):
        import io

        spec = importlib.util.spec_from_file_location(
            "origin", ROOT / "infra/deploy/configure-origin.py"
        )
        origin = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(origin)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nginx = root / "etc/nginx/nginx.conf"
            nginx.parent.mkdir(parents=True)
            nginx.write_text(
                "events {}\nhttp {\n server { listen 443 ssl; server_name 192.0.2.1; }\n}\n"
            )

            def mapped(path):
                return root / str(path).lstrip("/")

            ranges = {
                "prefixes": [
                    {
                        "service": "CLOUDFRONT_ORIGIN_FACING",
                        "ip_prefix": "192.0.2.0/24",
                    },
                    {"service": "EC2", "ip_prefix": "0.0.0.0/0"},
                ],
                "ipv6_prefixes": [],
            }
            with (
                patch.object(origin, "Path", mapped),
                patch.object(origin.subprocess, "run"),
                patch.object(
                    origin.urllib.request,
                    "urlopen",
                    side_effect=lambda *a, **k: io.BytesIO(json.dumps(ranges).encode()),
                ),
            ):
                origin.configure(
                    {"ip": "192.0.2.1", "email": "test@example.org"}, refresh_trust=True
                )
                first = nginx.read_text()
                origin.configure(
                    {"ip": "192.0.2.1", "email": "test@example.org"}, refresh_trust=True
                )
            self.assertEqual(first, nginx.read_text())
            self.assertGreater(
                first.index("include /etc/nginx/stayhub"),
                first.index("server_name 192.0.2.1"),
            )
            config = (root / "etc/nginx/stayhub/api.conf").read_text()
            self.assertIn("set_real_ip_from 192.0.2.0/24;", config)
            self.assertNotIn("set_real_ip_from 0.0.0.0/0;", config)
            self.assertIn("real_ip_recursive off;", config)
            self.assertIn("proxy_set_header X-Forwarded-For $remote_addr;", config)
            self.assertNotIn("index.html", config)


if __name__ == "__main__":
    unittest.main(verbosity=2)
