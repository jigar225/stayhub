"""Pytest-only storage boundary. No application runtime behavior is changed."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import boto3

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client

MANAGED_PREFIXES = ("stayhub/staging/", "stayhub/final/")


class UnsafeTestStorage(RuntimeError):
    pass


@dataclass(frozen=True)
class StorageIsolation:
    bucket: str
    internal_endpoint: str

    @classmethod
    def from_environment(
        cls, default_development_bucket: str, default_endpoint: str
    ) -> StorageIsolation:
        # Read the raw variable, never Settings.test_s3_bucket's convenient
        # application default: pytest must require explicit opt-in.
        bucket = os.environ.get("TEST_S3_BUCKET", "")
        development = os.environ.get("S3_BUCKET", default_development_bucket)
        if (
            not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", bucket)
            or not bucket.endswith("-test")
            or not development
            or bucket == development
        ):
            raise UnsafeTestStorage(
                "TEST_S3_BUCKET must be explicitly configured, distinct from the "
                "development bucket, and a lowercase alphanumeric/hyphen bucket "
                "name (3–63 characters) ending in -test."
            )
        return cls(bucket, os.environ.get("S3_ENDPOINT_URL", default_endpoint))

    def bind_environment(self) -> None:
        # Deliberately never restore development storage, even at session exit.
        os.environ["S3_BUCKET"] = self.bucket
        os.environ["S3_PUBLIC_ENDPOINT_URL"] = self.internal_endpoint

    def guard_parameters(self, params: dict[str, Any], **kwargs: Any) -> None:
        # This botocore event also runs for presigned URLs, before network I/O.
        if params.get("Bucket") != self.bucket:
            raise UnsafeTestStorage(
                "Pytest S3 operations require the pinned test bucket."
            )
        keys = [params["Key"]] if "Key" in params else []
        keys.extend(
            item.get("Key") for item in params.get("Delete", {}).get("Objects", [])
        )
        if "CopySource" in params or any(
            not isinstance(key, str) or not key.startswith(MANAGED_PREFIXES)
            for key in keys
        ):
            raise UnsafeTestStorage(
                "Pytest object operations require managed test prefixes."
            )

    def install_guard(self) -> None:
        # Application storage uses boto3's default session. Register before any
        # application import/client creation; its clients inherit this handler.
        if boto3.DEFAULT_SESSION is None:
            boto3.setup_default_session()
        assert boto3.DEFAULT_SESSION is not None
        boto3.DEFAULT_SESSION.events.register(
            "before-parameter-build.s3",
            self.guard_parameters,
            unique_id="stayhub-pytest-storage-isolation",
        )

    def purge_managed(self, client: S3Client) -> None:
        for prefix in MANAGED_PREFIXES:
            for page in client.get_paginator("list_objects_v2").paginate(
                Bucket=self.bucket, Prefix=prefix
            ):
                for item in page.get("Contents", []):
                    key = item["Key"]
                    if not key.startswith(prefix):
                        raise UnsafeTestStorage(
                            "Refusing cleanup outside the requested managed prefix."
                        )
                    client.delete_object(Bucket=self.bucket, Key=key)


@contextmanager
def storage_scope(
    isolation: StorageIsolation,
    reset_settings: Callable[[], None],
    *,
    initialize: bool = False,
) -> Iterator[None]:
    # Lazy imports: validation/binding/guard installation happen before app.main.
    from app import storage
    from app.storage_setup import setup_bucket

    def reset() -> None:
        isolation.bind_environment()
        reset_settings()

    reset()
    try:
        if initialize:
            setup_bucket(isolation.bucket)
        yield
    finally:
        try:
            reset()
            isolation.purge_managed(storage.s3_client())
        finally:
            # Also runs if setup, test body, client creation or cleanup raises.
            reset()
