"""Runs safely on its own: no fixture imports from any other test module."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any, cast
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from mypy_boto3_s3.client import S3Client
from storage_isolation import StorageIsolation, UnsafeTestStorage, storage_scope

from app import storage, storage_setup
from app.config import get_settings

IMPORT_TIME_BUCKET = get_settings().s3_bucket


def test_storage_is_automatic_without_a_fixture_import() -> None:
    settings = get_settings()
    assert IMPORT_TIME_BUCKET == settings.s3_bucket == os.environ["TEST_S3_BUCKET"]
    key = f"{storage.PREFIX}final/isolation-regression/{uuid4()}.png"
    content = b"test-only automatic isolation regression"
    storage.put_final(key, content, "image/png")
    result = storage.s3_client().get_object(Bucket=settings.s3_bucket, Key=key)
    try:
        assert result["Body"].read() == content
    finally:
        result["Body"].close()
    signed = storage.read_url(key)
    assert urlparse(signed).path == f"/{settings.s3_bucket}/{key}"


@pytest.mark.parametrize(
    "bucket",
    [
        None,
        "",
        "development-test",
        "no-test-suffix",
        "UPPER-test",
        "bad/name-test",
        "bad.name-test",
        " " + "safe-test",
        "x" * 64 + "-test",
    ],
    ids=[
        "missing",
        "empty",
        "equal",
        "suffix",
        "uppercase",
        "slash",
        "dot",
        "whitespace",
        "length",
    ],
)
def test_unsafe_configuration_stops_before_app_or_storage(bucket: str | None) -> None:
    env = dict(os.environ, S3_BUCKET="development-test")
    if bucket is None:
        env.pop("TEST_S3_BUCKET", None)
    else:
        env["TEST_S3_BUCKET"] = bucket
    # Separate interpreter tests the real conftest import order, not a cached
    # settings instance or a unit-only validator. Any client creation trips it.
    program = """import json,runpy,sys
import boto3
sys.path.insert(0, "tests")
clients=[]
def forbidden(*args, **kwargs):
    clients.append(True)
    raise AssertionError("Storage client created before unsafe config rejection")
boto3.client=forbidden
try:
    runpy.run_path("tests/conftest.py")
except RuntimeError as error:
    assert "TEST_S3_BUCKET" in str(error), str(error)
    assert not clients
    assert "app.main" not in sys.modules
    from app.config import get_settings
    assert get_settings.cache_info().currsize == 0
    print(json.dumps({"blocked":True,"storage_clients":0,"app_initialized":False}))
else:
    raise AssertionError("Unsafe storage configuration was accepted")
"""
    result = subprocess.run(
        [sys.executable, "-c", program],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "blocked": True,
        "storage_clients": 0,
        "app_initialized": False,
    }


def test_client_guard_blocks_wrong_bucket_and_presigning_before_io(
    monkeypatch: Any,
) -> None:
    sends: list[object] = []

    def forbidden(*args: Any, **kwargs: Any) -> None:
        sends.append(True)
        raise AssertionError("Network I/O should never be reached")

    monkeypatch.setattr("botocore.httpsession.URLLib3Session.send", forbidden)
    client = storage.s3_client()
    with pytest.raises(UnsafeTestStorage, match="pinned test bucket"):
        client.put_object(
            Bucket="never-contact-development",
            Key="stayhub/final/probe",
            Body=b"blocked",
        )
    with pytest.raises(UnsafeTestStorage, match="pinned test bucket"):
        client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": "never-contact-development",
                "Key": "stayhub/final/probe",
            },
        )
    with pytest.raises(UnsafeTestStorage, match="managed test prefixes"):
        client.delete_object(Bucket=get_settings().s3_bucket, Key="unmanaged/keep")
    assert not sends


class CleanupProbe:
    def __init__(self, unsafe: bool = False) -> None:
        self.operations: list[tuple[str, str]] = []
        self.unsafe = unsafe

    def get_paginator(self, operation: str) -> CleanupProbe:
        assert operation == "list_objects_v2"
        return self

    def paginate(self, *, Bucket: str, Prefix: str) -> list[dict[str, object]]:
        self.operations.append((Bucket, Prefix))
        return [
            {
                "Contents": [
                    {"Key": "unmanaged/keep" if self.unsafe else Prefix + "probe"}
                ]
            }
        ]

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        self.operations.append((Bucket, Key))


def test_cleanup_is_pinned_to_test_bucket_and_managed_prefixes() -> None:
    isolation = StorageIsolation(
        os.environ["TEST_S3_BUCKET"], get_settings().s3_endpoint_url
    )
    probe = CleanupProbe()
    isolation.purge_managed(cast(S3Client, probe))
    assert probe.operations == [
        (isolation.bucket, "stayhub/staging/"),
        (isolation.bucket, "stayhub/staging/probe"),
        (isolation.bucket, "stayhub/final/"),
        (isolation.bucket, "stayhub/final/probe"),
        (isolation.bucket, "stayhub/messages/"),
        (isolation.bucket, "stayhub/messages/probe"),
    ]
    unexpected = CleanupProbe(unsafe=True)
    with pytest.raises(UnsafeTestStorage, match="outside"):
        isolation.purge_managed(cast(S3Client, unexpected))
    assert unexpected.operations == [(isolation.bucket, "stayhub/staging/")]


@pytest.mark.parametrize("failure", ["setup", "body", "cleanup"])
def test_storage_failure_keeps_test_binding_and_clears_cached_settings(
    monkeypatch: Any,
    failure: str,
) -> None:
    isolation = StorageIsolation(
        os.environ["TEST_S3_BUCKET"], get_settings().s3_endpoint_url
    )
    cached = get_settings()
    probes: list[str] = []

    def initialize(bucket: str) -> None:
        assert bucket == isolation.bucket
        probes.append("setup")
        if failure == "setup":
            os.environ["S3_BUCKET"] = "never-restore-development"
            get_settings.cache_clear()
            get_settings()
            raise RuntimeError("injected setup failure")

    def purge(self: StorageIsolation, client: S3Client) -> None:
        assert get_settings().s3_bucket == isolation.bucket
        probes.append("cleanup")
        if failure == "cleanup":
            os.environ["S3_BUCKET"] = "never-restore-development"
            raise RuntimeError("injected cleanup failure")

    monkeypatch.setattr(storage_setup, "setup_bucket", initialize)
    monkeypatch.setattr(StorageIsolation, "purge_managed", purge)
    with pytest.raises(RuntimeError, match="injected"):
        with storage_scope(isolation, get_settings.cache_clear, initialize=True):
            if failure == "body":
                os.environ["S3_BUCKET"] = "never-restore-development"
                raise RuntimeError("injected body failure")
    assert probes == ["setup", "cleanup"]
    assert os.environ["S3_BUCKET"] == isolation.bucket
    assert get_settings.cache_info().currsize == 0
    assert get_settings() is not cached
    assert get_settings().s3_bucket == isolation.bucket
