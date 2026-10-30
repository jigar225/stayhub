"""Private S3 boundary. Keys are always server-generated, never client input."""

from __future__ import annotations

import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from PIL import Image, UnidentifiedImageError

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client

from app.config import get_settings
from app.errors import ApiError

MAX_SOURCE_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 20_000_000
MAX_DIMENSION = 8192
PREFIX = "stayhub/"


def s3_client(public: bool = False) -> S3Client:
    settings = get_settings()
    if not settings.s3_use_iam_role and (
        not settings.s3_access_key.get_secret_value()
        or not settings.s3_secret_key.get_secret_value()
    ):
        raise ApiError(
            503,
            "storage_unavailable",
            "Photo storage is not configured. Please retry later.",
        )
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_public_endpoint_url
        if public
        else settings.s3_endpoint_url,
        aws_access_key_id=None
        if settings.s3_use_iam_role
        else settings.s3_access_key.get_secret_value(),
        aws_secret_access_key=None
        if settings.s3_use_iam_role
        else settings.s3_secret_key.get_secret_value(),
        region_name=settings.s3_region,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=3,
            read_timeout=10,
            retries={"max_attempts": 1},
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


@contextmanager
def storage_errors() -> Iterator[None]:
    try:
        yield
    except (BotoCoreError, ClientError):
        raise ApiError(
            503,
            "storage_unavailable",
            "Photo storage is temporarily unavailable. Please retry.",
        ) from None


def upload_url(key: str, content_type: str, size: int) -> str:
    with storage_errors():
        return s3_client(public=True).generate_presigned_url(
            "put_object",
            Params={
                "Bucket": get_settings().s3_bucket,
                "Key": key,
                "ContentType": content_type,
                "ContentLength": size,
            },
            ExpiresIn=300,
        )


def read_url(key: str) -> str:
    with storage_errors():
        return s3_client(public=True).generate_presigned_url(
            "get_object",
            Params={"Bucket": get_settings().s3_bucket, "Key": key},
            ExpiresIn=300,
        )


def read_source(key: str, expected: int) -> bytes:
    with storage_errors():
        try:
            result = s3_client().get_object(Bucket=get_settings().s3_bucket, Key=key)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in {
                "NoSuchKey",
                "404",
                "NotFound",
            }:
                raise ApiError(
                    422, "upload_invalid", "Upload the image before completing it."
                ) from None
            raise
        stream = result["Body"]
        try:
            if result.get("ContentLength") != expected or expected > MAX_SOURCE_BYTES:
                raise ApiError(
                    422,
                    "upload_invalid",
                    "The uploaded size does not match this upload authorization.",
                )
            content = stream.read(MAX_SOURCE_BYTES + 1)
        finally:
            stream.close()
        if len(content) != expected or len(content) > MAX_SOURCE_BYTES:
            raise ApiError(
                422, "upload_invalid", "The uploaded image exceeds its allowed size."
            )
        return content


def verify_image(content: bytes, content_type: str) -> tuple[bytes, int, int]:
    expected = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}[
        content_type
    ]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as source:
                width, height = source.size
                if (
                    source.format != expected
                    or width * height > MAX_PIXELS
                    or max(width, height) > MAX_DIMENSION
                    or min(width, height) < 1
                ):
                    raise ValueError("format or dimensions")
                source.verify()
            with Image.open(BytesIO(content)) as source:
                source.load()
                # New pixel-only image drops EXIF, comments, ICC and other metadata.
                mode = (
                    "RGBA"
                    if expected in {"PNG", "WEBP"} and "A" in source.getbands()
                    else "RGB"
                )
                pixels = source.convert(mode)
                clean = Image.new(mode, pixels.size)
                clean.paste(pixels)
                output = BytesIO()
                clean.save(output, format=expected)
                encoded = output.getvalue()
                if len(encoded) > MAX_SOURCE_BYTES:
                    raise ValueError("encoded size")
                return encoded, width, height
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise ApiError(
            422,
            "upload_invalid",
            "Use a valid JPEG, PNG or WebP image up to 10 MiB, 20 million pixels and 8192 pixels per side, matching the selected type.",
        ) from None


def put_final(key: str, content: bytes, content_type: str) -> None:
    with storage_errors():
        s3_client().put_object(
            Bucket=get_settings().s3_bucket,
            Key=key,
            Body=content,
            ContentType=content_type,
            ContentLength=len(content),
        )


def delete_object_best_effort(key: str) -> bool:
    try:
        with storage_errors():
            s3_client().delete_object(Bucket=get_settings().s3_bucket, Key=key)
        return True
    except ApiError:
        return False
