"""Offline Geoapify secret/runtime checks. No AWS, provider or database calls."""

import contextlib
import io
import json
import os
import runpy
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"
KEY = "fake-provider-key-only-for-tests"


class RuntimeProviderTests(unittest.TestCase):
    def render(self, app, root):
        (root / "config.json").write_text(
            json.dumps(
                dict(
                    db_secret="db",
                    app_secret="app",
                    db_host="db.invalid",
                    ip="example.invalid",
                    photos="private-photos",
                )
            )
        )

        def execute(args, **kwargs):
            self.assertTrue(kwargs["capture_output"])
            value = (
                {"username": "test", "password": "fake-db-password"}
                if args[args.index("--secret-id") + 1] == "db"
                else app
            )
            return SimpleNamespace(returncode=0, stdout=json.dumps(value), stderr="")

        out, err = io.StringIO(), io.StringIO()
        with (
            patch.dict(os.environ, {"STAYHUB_ROOT": str(root)}),
            patch("subprocess.run", side_effect=execute),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            runpy.run_path(str(DEPLOY / "runtime-env.py"), run_name="__main__")
        self.assertEqual(out.getvalue() + err.getvalue(), "")
        return dict(
            line.split("=", 1)
            for line in (root / "runtime.env").read_text().splitlines()
        )

    def test_optional_missing_key_and_default_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            values = self.render({"JWT_SECRET": "x" * 40}, Path(temp))
            self.assertEqual(values["GEOAPIFY_API_KEY"], "")
            self.assertEqual(values["GEOAPIFY_DAILY_BUDGET"], "2800")

    def test_only_backend_allowlist_and_private_file_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "runtime.env").write_text("old")
            (root / "runtime.env").chmod(0o644)
            values = self.render(
                {
                    "JWT_SECRET": "x" * 40,
                    "GEOAPIFY_API_KEY": KEY,
                    "GEOAPIFY_DAILY_BUDGET": "1500",
                    "SEED_HOST_EMAIL": "host@example.invalid",
                    "VITE_GEOAPIFY_API_KEY": "do-not-forward",
                    "OTHER": "do-not-forward",
                },
                root,
            )
            self.assertEqual(values["GEOAPIFY_API_KEY"], KEY)
            self.assertEqual(values["GEOAPIFY_DAILY_BUDGET"], "1500")
            self.assertIn("SEED_HOST_EMAIL", values)
            self.assertNotIn("VITE_GEOAPIFY_API_KEY", values)
            self.assertNotIn("OTHER", values)
            self.assertEqual(stat.S_IMODE((root / "runtime.env").stat().st_mode), 0o600)

    def test_invalid_values_preserve_existing_runtime(self):
        for overrides in [
            {"GEOAPIFY_API_KEY": KEY + "\nINJECTED=1"},
            {"GEOAPIFY_API_KEY": True},
            {"GEOAPIFY_DAILY_BUDGET": True},
            {"GEOAPIFY_DAILY_BUDGET": 3001},
            {"GEOAPIFY_DAILY_BUDGET": 0},
            {"GEOAPIFY_DAILY_BUDGET": "2.5"},
        ]:
            with (
                self.subTest(overrides=overrides),
                tempfile.TemporaryDirectory() as temp,
            ):
                root = Path(temp)
                (root / "runtime.env").write_text("preserved")
                with self.assertRaises(ValueError) as error:
                    self.render({"JWT_SECRET": "x" * 40, **overrides}, root)
                self.assertNotIn(KEY, str(error.exception))
                self.assertEqual((root / "runtime.env").read_text(), "preserved")


class OperatorProviderTests(unittest.TestCase):
    def invoke(self, inputs, *, fail=None):
        existing = {
            "JWT_SECRET": "x" * 40,
            "SEED_HOST_PASSWORD": "fake-seed-value",
            "OTHER_FIELD": "preserve-me",
        }
        submitted = []
        paths = []

        def execute(args, **kwargs):
            self.assertTrue(kwargs["capture_output"])
            self.assertNotIn(KEY, " ".join(args))
            if args[0] == "terraform":
                value = {"app_secret": "app-arn"}
            elif "get-secret-value" in args:
                value = existing
            else:
                path = Path(args[-1].removeprefix("file://"))
                paths.append(path)
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                submitted.append(
                    json.loads(json.loads(path.read_text())["SecretString"])
                )
                value = {}
            if fail and fail in args:
                return SimpleNamespace(returncode=1, stdout=KEY, stderr=KEY)
            return SimpleNamespace(returncode=0, stdout=json.dumps(value), stderr="")

        out, err = io.StringIO(), io.StringIO()
        failure = None
        with (
            patch("subprocess.run", side_effect=execute),
            patch("getpass.getpass", side_effect=inputs),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            try:
                runpy.run_path(
                    str(DEPLOY / "configure-geoapify-secret.py"), run_name="__main__"
                )
            except SystemExit as error:
                failure = str(error)
        self.assertNotIn(KEY, out.getvalue() + err.getvalue() + (failure or ""))
        self.assertTrue(all(not p.exists() for p in paths))
        return submitted, failure

    def test_private_prompt_write_preserves_all_existing_fields(self):
        submitted, failure = self.invoke([KEY, ""])
        self.assertIsNone(failure)
        self.assertEqual(len(submitted), 1)
        self.assertEqual(submitted[0]["GEOAPIFY_API_KEY"], KEY)
        self.assertEqual(submitted[0]["GEOAPIFY_DAILY_BUDGET"], 2800)
        self.assertEqual(submitted[0]["OTHER_FIELD"], "preserve-me")
        self.assertEqual(submitted[0]["SEED_HOST_PASSWORD"], "fake-seed-value")
        self.assertEqual(submitted[0]["JWT_SECRET"], "x" * 40)

    def test_empty_key_leaves_secret_unchanged(self):
        submitted, failure = self.invoke([""])
        self.assertFalse(submitted)
        self.assertIsNone(failure)

    def test_invalid_budget_does_not_write(self):
        submitted, failure = self.invoke([KEY, "3001"])
        self.assertFalse(submitted)
        self.assertIn("No secret values displayed", failure)

    def test_aws_failure_is_redacted_and_private_file_removed(self):
        _, failure = self.invoke([KEY, "100"], fail="put-secret-value")
        self.assertIn("No secret values displayed", failure)


if __name__ == "__main__":
    unittest.main(verbosity=2)
