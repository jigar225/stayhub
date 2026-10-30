"""Offline credential-boundary checks; no Postgres, S3 or AWS calls."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app import storage
from app.config import Settings


class StorageCredentialsTest(unittest.TestCase):
    def settings(self, **overrides):
        return Settings(
            database_url="postgresql://unused",
            jwt_secret="x" * 40,
            s3_access_key="",
            s3_secret_key="",
            **overrides,
        )

    def test_iam_mode_uses_sdk_credential_chain(self):
        settings = self.settings(s3_use_iam_role=True)
        with (
            patch.object(storage, "get_settings", return_value=settings),
            patch.object(storage.boto3, "client") as client,
        ):
            storage.s3_client()
            self.assertIsNone(client.call_args.kwargs["aws_access_key_id"])
            self.assertIsNone(client.call_args.kwargs["aws_secret_access_key"])

    def test_local_mode_still_rejects_missing_credentials(self):
        with patch.object(
            storage, "get_settings", return_value=self.settings(s3_use_iam_role=False)
        ):
            with self.assertRaises(storage.ApiError) as result:
                storage.s3_client()
            self.assertEqual(result.exception.status, 503)

    def test_local_credentials_are_preserved(self):
        settings = Settings(
            database_url="postgresql://unused",
            jwt_secret="x" * 40,
            s3_use_iam_role=False,
            s3_access_key="local-key",
            s3_secret_key="local-secret",
        )
        with (
            patch.object(storage, "get_settings", return_value=settings),
            patch.object(storage.boto3, "client") as client,
        ):
            storage.s3_client()
            self.assertEqual(client.call_args.kwargs["aws_access_key_id"], "local-key")
            self.assertEqual(
                client.call_args.kwargs["aws_secret_access_key"], "local-secret"
            )


if __name__ == "__main__":
    unittest.main()
